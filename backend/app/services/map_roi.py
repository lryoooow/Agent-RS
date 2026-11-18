"""Bounded, georeferenced map-image acquisition for a user-selected ROI.

Uses the map service's supported Export Map operation (not an offline tile
export). Labels are a separate source and never enter the analysis image.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import math
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from app.core.error_logging import log_exception_diagnostics
from app.core.paths import imagery_root
from app.core.resource_limits import resource_semaphore
from app.services.imagery_persist import _extract_metadata, _file_sha256, _persist_imagery_record, await_settled_operation

MAP_SERVICE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer'
ATTRIBUTION = 'Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community'
MAX_PIXELS = 2048
MAX_BYTES = 24 * 1024 * 1024
_FETCH_BUDGET = 55.0
_RETRY_DELAY = 0.5
_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}
_QUEUE_BUDGET = 10.0
logger = logging.getLogger(__name__)


class MapROIError(ValueError):
    def __init__(self, message: str, *, code: str = 'map_image_unavailable', retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def map_roi_plan(bbox) -> dict:
    if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4 or
        not all(type(v) in (int, float) and math.isfinite(v) for v in bbox)):
        raise MapROIError('地图选区无效，请重新框选。')
    w,s,e,n = bbox
    if not (-180 <= w < e <= 180 and -85 <= s < n <= 85):
        raise MapROIError('当前地图选区超出支持范围，请重新框选。')
    radius = 6378137.0
    def y(lat): return radius * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    extent = [radius*math.radians(w), y(s), radius*math.radians(e), y(n)]
    dx,dy = extent[2]-extent[0], extent[3]-extent[1]
    sample = max(2*math.pi*radius/(256*2**18), dx/MAX_PIXELS, dy/MAX_PIXELS)
    ground_sample = sample * math.cos(math.radians((s+n)/2))
    if ground_sample > 2:
        raise MapROIError('选区过大，请缩小范围以保留分析所需的影像细节。')
    width,height = max(1,math.ceil(dx/sample)),max(1,math.ceil(dy/sample))
    if min(width,height) < 16:
        raise MapROIError('选区过窄，请扩大选区后提取。')
    return dict(bbox=list(bbox), extent=extent, width=width, height=height, sample_m=ground_sample)


def _validate_image_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise MapROIError('地图服务返回了无法验证的影像地址。', code='map_url_invalid') from exc
    path = unquote(parsed.path)
    if (parsed.scheme != 'https' or parsed.hostname != 'server.arcgisonline.com' or
        port not in (None,443) or parsed.username or parsed.password or '\\' in path or '..' in path.split('/') or
        not path.lower().startswith('/arcgis/rest/directories/arcgisoutput/world_imagery_mapserver/')):
        raise MapROIError('地图服务返回了无法验证的影像地址。', code='map_url_invalid')
    return url


async def _fetch_export(client: httpx.AsyncClient, plan: dict) -> dict:
    response = await client.get(MAP_SERVICE+'/export', params={
        'bbox':','.join(map(str,plan['extent'])), 'bboxSR':3857, 'imageSR':3857,
        'size':f"{plan['width']},{plan['height']}", 'format':'png32', 'transparent':'true', 'f':'json',
    })
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise MapROIError('底图服务返回的导出信息无法解析。', code='map_export_invalid') from exc
    if not isinstance(data, dict):
        raise MapROIError('底图服务返回的导出信息格式无效。', code='map_export_invalid')
    if error := data.get('error'):
        # ArcGIS can report a service error inside a successful HTTP response.
        status = error.get('code') if isinstance(error, dict) else None
        if type(status) is int and 400 <= status <= 599:
            raise MapROIError(f'请求底图导出时，服务返回错误代码 {status}。',
                              code=f'map_export_{status}', retryable=status in _TRANSIENT_STATUS)
        raise MapROIError('底图服务未能导出选区影像。', code='map_export_rejected')
    if not isinstance(data.get('href'), str):
        raise MapROIError('底图服务未提供选区影像的下载地址。', code='map_export_invalid')
    _validate_image_url(data['href'])
    extent = data.get('extent')
    sr = extent.get('spatialReference') if isinstance(extent, dict) else None
    values = [extent.get(k) for k in ('xmin','ymin','xmax','ymax')] if isinstance(extent, dict) else []
    if (not isinstance(sr, dict) or (sr.get('latestWkid') or sr.get('wkid')) not in (3857,102100) or
        not all(type(v) in (float, int) and math.isfinite(v) for v in values)):
        raise MapROIError('地图影像缺少有效地理范围。', code='map_extent_invalid')
    if not all(type(data.get(k)) is int and 0 < data[k] <= MAX_PIXELS for k in ('width','height')):
        raise MapROIError('地图服务返回的影像尺寸不符合请求。', code='map_size_invalid')
    # Export Map may slightly expand one axis to match the requested aspect ratio.
    px = max((plan['extent'][2]-plan['extent'][0])/plan['width'],(plan['extent'][3]-plan['extent'][1])/plan['height'])
    if values[0] >= values[2] or values[1] >= values[3] or any(abs(v-p) > px*3 for v,p in zip(values,plan['extent'])):
        raise MapROIError('地图影像返回范围与选区不一致。', code='map_extent_invalid')
    return data


async def _fetch_image(client: httpx.AsyncClient, url: str) -> bytes:
    content = bytearray()
    async with client.stream('GET', url) as response:
        response.raise_for_status()
        if not response.headers.get('content-type','').lower().startswith('image/'):
            raise MapROIError('底图服务返回的文件缺少影像格式。', code='map_image_invalid')
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > MAX_BYTES:
                raise MapROIError('地图影像过大，请缩小选区。', code='map_image_too_large')
            content.extend(chunk)
    return bytes(content)


def _fetch_error(exc: httpx.HTTPError | MapROIError, phase: str) -> MapROIError:
    if isinstance(exc, MapROIError):
        return exc
    step = '请求底图导出' if phase == 'export' else '下载选区影像'
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return MapROIError(f'{step}时底图服务返回 HTTP {status}。',
            code=f'map_{phase}_http_{status}', retryable=status in _TRANSIENT_STATUS)
    if isinstance(exc, httpx.TimeoutException):
        return MapROIError(f'{step}时等待底图服务超时。', code=f'map_{phase}_timeout', retryable=True)
    return MapROIError(f'{step}时与底图服务的通信失败。', code=f'map_{phase}_network',
        retryable=isinstance(exc, (httpx.NetworkError, httpx.RemoteProtocolError)))


async def _download_map(plan: dict) -> tuple[bytes, dict]:
    started = time.monotonic()
    phase = 'export'
    attempt = 1
    exported = None
    try:
        async with asyncio.timeout(_FETCH_BUDGET), httpx.AsyncClient(
            timeout=httpx.Timeout(20, connect=8), trust_env=False, follow_redirects=False,
        ) as client:
            while True:
                try:
                    if exported is None:
                        exported = await _fetch_export(client, plan)
                    phase = 'download'
                    return await _fetch_image(client, exported['href']), exported
                except (httpx.HTTPError, MapROIError) as exc:
                    error = _fetch_error(exc, phase)
                    logger.warning('map_roi.fetch phase=%s attempt=%d code=%s exception=%s elapsed_ms=%d',
                        phase, attempt, error.code, type(exc).__name__, (time.monotonic()-started)*1000)
                    # A service-requested cooldown may outlast this chat turn.
                    # Return control to the user instead of retrying ahead of it.
                    cooldown = isinstance(exc, httpx.HTTPStatusError) and exc.response.headers.get('Retry-After') not in (None, '0')
                    if not error.retryable or cooldown or attempt == 2:
                        raise error
                    await asyncio.sleep(_RETRY_DELAY)
                    attempt += 1
    except TimeoutError as exc:
        logger.warning('map_roi.fetch phase=%s attempt=%d code=map_fetch_deadline elapsed_ms=%d',
            phase, attempt, (time.monotonic()-started)*1000)
        raise MapROIError('获取选区底图超过等待时限。', code='map_fetch_deadline', retryable=True) from exc


def _write_raster(dest: Path, content: bytes, exported: dict, plan: dict) -> dict:
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.enums import ColorInterp, Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import calculate_default_transform, reproject
    from app.services.raster_semantics import grid_context

    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.size != (exported['width'],exported['height']):
                raise MapROIError('地图影像尺寸与地理信息不一致。', code='map_size_invalid')
            rgba = np.asarray(image.convert('RGBA'))
    except (OSError, Image.DecompressionBombError) as exc:
        raise MapROIError('下载的底图影像无法解码。', code='map_image_invalid') from exc
    if not (rgba[:,:,3] > 0).any():
        raise MapROIError('此区域没有可用的地图影像，未启动提取。')
    extent = exported['extent']
    bounds = [extent[k] for k in ('xmin','ymin','xmax','ymax')]
    src_transform = from_bounds(*bounds,exported['width'],exported['height'])
    w,s,e,n = plan['bbox']
    zone = min(60,max(1,int(((w+e)/2+180)//6)+1))
    crs = f"EPSG:{(32600 if (s+n)/2 >= 0 else 32700)+zone}"
    transform,width,height = calculate_default_transform('EPSG:3857',crs,exported['width'],exported['height'],*bounds)
    if max(width,height) > MAX_PIXELS*2:
        raise MapROIError('选区投影范围异常，请缩小选区。')
    output = np.zeros((4,height,width),dtype='uint8')
    for band in range(4):
        reproject(rgba[:,:,band],output[band],src_transform=src_transform,src_crs='EPSG:3857',
            dst_transform=transform,dst_crs=crs,resampling=Resampling.nearest if band==3 else Resampling.bilinear)
    with rasterio.open(dest/'source.tif','w',driver='GTiff',width=width,height=height,count=4,dtype='uint8',
        crs=crs,transform=transform,compress='deflate') as dst:
        dst.write(output)
        dst.colorinterp=(ColorInterp.red,ColorInterp.green,ColorInterp.blue,ColorInterp.alpha)
        for band,label in enumerate(('Red','Green','Blue','Alpha'),1): dst.set_band_description(band,label)
        dst.update_tags(SOURCE=MAP_SERVICE, ATTRIBUTION=ATTRIBUTION, SOURCE_KIND='map_rendered_rgb',
            REQUESTED_ROI=json.dumps(plan['bbox']), ACQUISITION_DATE='unknown')
    shutil.copy2(dest/'source.tif',dest/'working.tif')
    (dest/'results').mkdir()
    meta = _extract_metadata(dest/'working.tif')
    meta.update(grid_context(dest/'working.tif'))
    # Use the map export as the preview, preserving its geographic extent;
    # a projected UTM image cannot be stretched over four lon/lat corners.
    from rasterio.warp import transform_bounds
    meta['bounds'] = list(transform_bounds('EPSG:3857','EPSG:4326',*bounds))
    preview = Image.fromarray(rgba)
    preview.thumbnail((1024,1024))
    preview.save(dest/'results'/'preview.png')
    # Grid sampling is not the source sensor's native resolution. Never invent
    # an acquisition date or NIR/SWIR from an RGB basemap.
    meta.update(source_origin='map_roi', map_source='esri_world_imagery', source_url=MAP_SERVICE,
        attribution=ATTRIBUTION, requested_roi=plan['bbox'], source_native_resolution_known=False,
        native_resolution_m=None, acquired_at=None, sensor=None, band_roles={'red':1,'green':2,'blue':3},
        band_roles_source='map_export_rgb', alpha_bands=[4], rendered_map_image=True)
    return meta


async def import_map_roi(bbox, *, user_id: str) -> tuple[str, dict]:
    try:
        return await _import_map_roi(bbox, user_id=user_id)
    except MapROIError:
        raise
    except Exception as exc:
        diagnostic = log_exception_diagnostics(logger, 'map_roi.import_failed', exc)
        raise MapROIError(f'平台未能准备好选区底图。诊断编号 {diagnostic}。', code='map_import_failed') from exc


async def _import_map_roi(bbox, *, user_id: str) -> tuple[str, dict]:
    # Agent tools also import this service; resolve their shared lock only at runtime.
    from app.agent.stac_search.composition_cache import async_file_lock
    from app.agent.stac_search.raster import SceneRasterError

    if not user_id:
        raise MapROIError('请先登录后分析地图选区。')
    plan = map_roi_plan(bbox)
    day = datetime.now(timezone.utc).date().isoformat()
    key = hashlib.sha256(json.dumps([user_id,day,'map-export-v2',plan],sort_keys=True).encode()).hexdigest()[:12]
    root = imagery_root(create=True).resolve()
    dest = root/key
    cached = _cached_map_roi(dest, user_id)
    if cached is not None:
        return key, cached
    locks = root / '.map-roi-locks'
    if locks.is_symlink() or locks.resolve().parent != root:
        raise MapROIError('地图影像锁目录无效。', code='map_storage_invalid')
    # The per-user file lock also serializes quota checks across worker processes.
    lock = locks / (hashlib.sha256(user_id.encode()).hexdigest() + '.lock')
    deadline = time.monotonic() + _QUEUE_BUDGET
    gate = resource_semaphore('map_roi_import', 2)
    try:
        async with async_file_lock(lock, timeout=_QUEUE_BUDGET):
            cached = _cached_map_roi(dest, user_id)
            if cached is not None:
                return key, cached
            if dest.exists():
                raise MapROIError('该选区存在尚未完成的导入记录，请检查影像存储状态。', code='map_import_incomplete')
            from app.agent.imagery_access import iter_user_imagery_metadata
            entries = await iter_user_imagery_metadata(user_id)
            if sum(m.get('source_origin')=='map_roi' and str(m.get('created_at','')).startswith(day) for _,m in entries) >= 60:
                raise MapROIError('今日地图选区影像数量已达上限，请复用已生成的选区影像。')
            try:
                await asyncio.wait_for(gate.acquire(), timeout=max(0, deadline-time.monotonic()))
            except TimeoutError as exc:
                raise MapROIError('地图取图任务排队超时，请稍后重试。', code='map_import_busy', retryable=True) from exc
            try:
                content, exported = await _download_map(plan)
                dest.mkdir(exist_ok=False)
                try:
                    # Metadata is uploaded before registration finishes. Keep it
                    # out of the fast cache path until both steps have settled.
                    pending = dest / '.importing'
                    pending.touch(exist_ok=False)
                    meta = await await_settled_operation(asyncio.to_thread(_write_raster,dest,content,exported,plan))
                    meta.update(imagery_id=key, filename=f'地图选区_{day}_{key}.tif', sha256=_file_sha256(dest/'source.tif'),
                        owner_user_id=user_id, created_at=datetime.now(timezone.utc).isoformat(),
                        preview_url=f'/api/imagery/{key}/results/preview.png', working_width=meta['width'],working_height=meta['height'],
                        compressed=False, compression_ratio=1.0,source_size_bytes=(dest/'source.tif').stat().st_size,
                        working_size_bytes=(dest/'working.tif').stat().st_size)
                    (dest/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
                    await _persist_imagery_record(key,dest,meta,user_id)
                    pending.unlink()
                except BaseException as exc:
                    if not getattr(exc, 'preserve_local_directory', False) and dest.resolve().parent == root and not dest.is_symlink():
                        shutil.rmtree(dest,ignore_errors=True)
                    raise
                return key, meta
            finally:
                gate.release()
    except SceneRasterError as exc:
        raise MapROIError('当前用户的地图取图任务仍在处理，请稍后重试。', code='map_import_busy', retryable=True) from exc


def _cached_map_roi(dest: Path, user_id: str) -> dict | None:
    if (dest / '.importing').exists() or not (dest / 'metadata.json').is_file():
        return None
    meta = json.loads((dest / 'metadata.json').read_text(encoding='utf-8'))
    if meta.get('owner_user_id') != user_id or meta.get('source_origin') != 'map_roi':
        raise MapROIError('地图影像缓存归属不匹配。')
    return meta

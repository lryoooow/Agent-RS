"""Bounded, georeferenced map-image acquisition for a user-selected ROI.

Uses the map service's supported Export Map operation (not an offline tile
export). Labels are a separate source and never enter the analysis image.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.core.paths import imagery_root
from app.services.imagery_persist import _extract_metadata, _file_sha256, _persist_imagery_record

MAP_SERVICE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer'
ATTRIBUTION = 'Source: Esri, Vantor, Earthstar Geographics, and the GIS User Community'
MAX_PIXELS = 2048
MAX_BYTES = 24 * 1024 * 1024
_IMPORT_GATE = asyncio.Semaphore(1)


class MapROIError(ValueError):
    pass


def map_roi_plan(bbox) -> dict:
    if not bbox or len(bbox) != 4 or not all(math.isfinite(v) for v in bbox):
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
        raise MapROIError('选区过大，无法保留建筑识别所需的细节；请缩小选区后直接提取。')
    width,height = max(1,math.ceil(dx/sample)),max(1,math.ceil(dy/sample))
    if min(width,height) < 16:
        raise MapROIError('选区过窄，请扩大选区后提取。')
    return dict(bbox=list(bbox), extent=extent, width=width, height=height, sample_m=ground_sample)


def _validate_image_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'server.arcgisonline.com' or
        parsed.port not in (None,443) or parsed.username or parsed.password or
        not parsed.path.lower().startswith('/arcgis/rest/directories/arcgisoutput/world_imagery_mapserver/')):
        raise MapROIError('地图服务返回了无法验证的影像地址。')
    return url


async def _download_map(plan: dict) -> tuple[bytes, dict]:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60,connect=15), trust_env=False, follow_redirects=False) as client:
        response = await client.get(MAP_SERVICE+'/export', params={
            'bbox':','.join(map(str,plan['extent'])), 'bboxSR':3857, 'imageSR':3857,
            'size':f"{plan['width']},{plan['height']}", 'format':'png32', 'transparent':'true', 'f':'json',
        })
        response.raise_for_status()
        data = response.json()
        if data.get('error') or not data.get('href'):
            raise MapROIError('当前地图影像获取失败，请稍后再试；未启动提取。')
        url = _validate_image_url(data['href'])
        extent = data.get('extent') or {}
        sr = extent.get('spatialReference') or {}
        values = [extent.get(k) for k in ('xmin','ymin','xmax','ymax')]
        if ((sr.get('latestWkid') or sr.get('wkid')) not in (3857,102100) or
            not all(isinstance(v,(float,int)) and math.isfinite(v) for v in values)):
            raise MapROIError('地图影像缺少有效地理范围，未启动提取。')
        if not all(isinstance(data.get(k),int) and 0 < data[k] <= MAX_PIXELS for k in ('width','height')):
            raise MapROIError('地图服务返回的影像尺寸不符合请求。')
        # Export Map may slightly expand one axis to match the requested aspect
        # ratio. Use the returned extent, but reject unrelated/oversized extents.
        px = max((plan['extent'][2]-plan['extent'][0])/plan['width'],(plan['extent'][3]-plan['extent'][1])/plan['height'])
        if any(abs(v-p) > px*3 for v,p in zip(values,plan['extent'])):
            raise MapROIError('地图影像返回范围与选区不一致，未启动提取。')
        chunks, total = [], 0
        async with client.stream('GET',url) as image_response:
            image_response.raise_for_status()
            if not image_response.headers.get('content-type','').startswith('image/'):
                raise MapROIError('地图服务未返回有效影像。')
            async for chunk in image_response.aiter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise MapROIError('地图影像过大，请缩小选区。')
                chunks.append(chunk)
        return b''.join(chunks), data


def _write_raster(dest: Path, content: bytes, exported: dict, plan: dict) -> dict:
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.enums import ColorInterp, Resampling
    from rasterio.transform import from_bounds
    from rasterio.warp import calculate_default_transform, reproject
    from app.services.raster_semantics import grid_context

    with Image.open(io.BytesIO(content)) as image:
        if image.size != (exported['width'],exported['height']):
            raise MapROIError('地图影像尺寸与地理信息不一致。')
        rgba = np.asarray(image.convert('RGBA'))
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
    if not user_id:
        raise MapROIError('请先登录后分析地图选区。')
    plan = map_roi_plan(bbox)
    day = datetime.now(timezone.utc).date().isoformat()
    key = hashlib.sha256(json.dumps([user_id,day,'map-export-v2',plan],sort_keys=True).encode()).hexdigest()[:12]
    root = imagery_root(create=True).resolve()
    dest = root/key
    async with _IMPORT_GATE:
        if (dest/'metadata.json').is_file():
            meta = json.loads((dest/'metadata.json').read_text())
            if meta.get('owner_user_id') != user_id or meta.get('source_origin') != 'map_roi':
                raise MapROIError('地图影像缓存归属不匹配。')
            return key,meta
        from app.agent.imagery_access import iter_user_imagery_metadata
        entries = await iter_user_imagery_metadata(user_id)
        if sum(m.get('source_origin')=='map_roi' and str(m.get('created_at','')).startswith(day) for _,m in entries) >= 60:
            raise MapROIError('今日地图选区影像数量已达上限，请复用已生成的选区影像。')
        try:
            content,exported = await _download_map(plan)
        except (httpx.HTTPError,ValueError,KeyError) as exc:
            if isinstance(exc,MapROIError): raise
            raise MapROIError('当前地图影像获取失败，请稍后再试；未启动提取。') from exc
        dest.mkdir(exist_ok=False)
        try:
            worker = asyncio.create_task(asyncio.to_thread(_write_raster,dest,content,exported,plan))
            try:
                meta = await asyncio.shield(worker)
            except asyncio.CancelledError:
                await worker
                raise
            meta.update(imagery_id=key, filename=f'地图选区_{day}_{key}.tif', sha256=_file_sha256(dest/'source.tif'),
                owner_user_id=user_id, created_at=datetime.now(timezone.utc).isoformat(),
                preview_url=f'/api/imagery/{key}/results/preview.png', working_width=meta['width'],working_height=meta['height'],
                compressed=False, compression_ratio=1.0,source_size_bytes=(dest/'source.tif').stat().st_size,
                working_size_bytes=(dest/'working.tif').stat().st_size)
            (dest/'metadata.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
            await _persist_imagery_record(key,dest,meta,user_id)
        except BaseException:
            if dest.parent == root and dest.name == key:
                shutil.rmtree(dest,ignore_errors=True)
            raise
        return key,meta

"""免账号卫星影像检索 API（Phase 7B）。

三件事：
- `POST /scenes/search`：区域（bbox 或地名）+ 时间 + 云量 → 场景卡片列表
- `GET  /scenes/{key}/preview|download`：服务端从远程 COG 生成的预览 PNG /
  多波段 GeoTIFF（窗口像素封顶）
- `POST /scenes/{key}/import`：合成影像注册进影像库（走上传同一套目录约定
  与归属登记），导入后即可被现有分析工具使用

安全与可用性：
- 场景 key 只存在于 user_id 隔离的服务端缓存（TTL 30 分钟），过期/越权一律
  404 让用户重搜——没有可枚举的稳定资源；
- 出网端点硬编码白名单（见 stac_search.sources），本路由不接受任何 URL 参数；
- 预览/下载/导入做按用户的滑动窗口限流，场景产物目录有文件数上限，
  超限删最旧，防止磁盘被刷满。
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import shutil
import time
from collections import deque
from functools import partial
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.agent.geocode import forward_geocode
from app.agent.stac_search import search_scenes
from app.agent.stac_search.cache import get_scene, put_scenes
from app.agent.stac_search.raster import SceneRasterError, compose_scene_tif, render_scene_preview
from app.agent.stac_search.importer import SceneImportError, import_scene_as_imagery
from app.agent.stac_search.sources import StacSearchError
from app.api.deps import require_authenticated_user
from app.api.routes.imagery import _extract_metadata, _file_sha256, _persist_imagery_record
from app.core.paths import imagery_root, scenes_root
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/scenes", tags=["scenes"])

_SCENE_KEY_PATTERN = "^[a-f0-9]{12}$"

# 滑动窗口限流：每用户每小时最多 40 次「预览之后的重活」（下载/导入）。
# 预览本身轻（降采样读 + 磁盘缓存），只与搜索共享回合外无限制——真正的
# 流量闸门是下载/导入的窗口像素封顶。
_HEAVY_OPS_PER_HOUR = 40
_HEAVY_WINDOWS: dict[str, deque[float]] = {}

# 每用户场景产物文件数上限（预览 PNG + 合成 TIF 合计），超限删最旧。
_MAX_SCENE_FILES_PER_USER = 60


class SceneSearchRequest(BaseModel):
    bbox: list[float] | None = Field(default=None, description="[w,s,e,n] EPSG:4326")
    place: str | None = Field(default=None, max_length=200, description="地名（服务端解析为范围）")
    start_date: str | None = Field(default=None, description="YYYY-MM-DD")
    end_date: str | None = Field(default=None, description="YYYY-MM-DD")
    cloud_max: float | None = Field(default=None, ge=0, le=100)
    source: Literal["auto", "sentinel2", "landsat"] = "auto"
    limit: int = Field(default=8, ge=1, le=20)


class SceneCard(BaseModel):
    key: str
    satellite: str
    item_id: str
    datetime: str
    cloud_cover: float | None
    bbox: list[float]
    resolution_m: float | None
    display_name: str
    preview_url: str
    download_url: str


def _scene_card(key: str, *, satellite: str, item_id: str, datetime_: str,
                cloud_cover: float | None, bbox: list[float], resolution_m: float | None,
                display_name: str) -> SceneCard:
    return SceneCard(
        key=key, satellite=satellite, item_id=item_id, datetime=datetime_,
        cloud_cover=cloud_cover, bbox=bbox, resolution_m=resolution_m,
        display_name=display_name,
        preview_url=f"/api/scenes/{key}/preview",
        download_url=f"/api/scenes/{key}/download",
    )


def _user_scene_dir(user_id: str, key: str) -> Path:
    return scenes_root(create=True) / user_id / key


def _enforce_scene_file_cap(user_id: str) -> None:
    user_root = scenes_root(create=True) / user_id
    if not user_root.exists():
        return
    files = sorted(
        (p for p in user_root.rglob("*") if p.is_file()),
        key=lambda p: p.stat().st_mtime,
    )
    excess = len(files) - _MAX_SCENE_FILES_PER_USER
    for path in files[: max(0, excess)]:
        _safe_unlink(path)
    # 清掉空 key 目录。
    for child in user_root.iterdir():
        if child.is_dir() and not any(child.iterdir()):
            _safe_unlink_dir(child)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove scene artifact: %s", path, exc_info=True)


def _safe_unlink_dir(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _require_heavy_quota(user_id: str) -> None:
    now = time.monotonic()
    window = _HEAVY_WINDOWS.setdefault(user_id, deque())
    while window and now - window[0] > 3600:
        window.popleft()
    if len(window) >= _HEAVY_OPS_PER_HOUR:
        raise HTTPException(status_code=429, detail="影像下载/导入过于频繁，请稍后再试。")
    window.append(now)


def _get_record_or_404(user_id: str, key: str):
    if len(key) != 12 or not all(c in "0123456789abcdef" for c in key):
        raise HTTPException(status_code=404, detail="场景不存在。")
    record = get_scene(user_id, key)
    if record is None:
        raise HTTPException(status_code=404, detail="场景已过期或不存在，请重新搜索。")
    return record


@router.post("/search", response_model=dict)
async def search_scene_cards(
    request: SceneSearchRequest,
    user_id: str = Depends(require_authenticated_user),
) -> dict:
    """检索免账号数据源（Sentinel-2 / Landsat），结果进服务端缓存。"""
    if not request.bbox and not (request.place or "").strip():
        raise HTTPException(status_code=400, detail="检索必须提供矩形范围或地名。")
    if request.bbox is not None and len(request.bbox) != 4:
        raise HTTPException(status_code=400, detail="bbox 必须是 [west, south, east, north] 四元组。")
    bbox = request.bbox
    if bbox is None:
        geo = await forward_geocode((request.place or "").strip())
        if geo is None:
            raise HTTPException(status_code=400, detail=f"无法解析地名「{request.place}」，请改用矩形范围。")
        center = geo["center"]
        # 地名检索给中心点 ±0.15° 的默认范围（城市尺度），用户可用 bbox 精确控制。
        bbox = [center[0] - 0.15, center[1] - 0.15, center[0] + 0.15, center[1] + 0.15]

    try:
        records, notes = await search_scenes(
            bbox=bbox,
            start_date=request.start_date,
            end_date=request.end_date,
            cloud_max=request.cloud_max,
            source=request.source,
            limit=request.limit,
        )
    except StacSearchError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    put_scenes(user_id, records)
    cards = [
        _scene_card(
            r.key, satellite=r.satellite, item_id=r.item_id, datetime_=r.datetime,
            cloud_cover=r.cloud_cover, bbox=r.bbox, resolution_m=r.resolution_m,
            display_name=r.display_name,
        )
        for r in records
    ]
    return {"scenes": [card.model_dump() for card in cards], "notes": notes}


@router.get("/{key}/preview")
async def scene_preview(
    key: str,
    user_id: str = Depends(require_authenticated_user),
) -> FileResponse:
    record = _get_record_or_404(user_id, key)
    out = _user_scene_dir(user_id, key) / "preview.png"
    try:
        # 远程 COG 读取是同步阻塞（GDAL），放线程池避免卡事件循环。
        await asyncio.to_thread(render_scene_preview, record, out)
    except SceneRasterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return FileResponse(out, media_type="image/png")


@router.get("/{key}/download")
async def scene_download(
    key: str,
    bbox: list[float] | None = Query(default=None),
    user_id: str = Depends(require_authenticated_user),
) -> FileResponse:
    record = _get_record_or_404(user_id, key)
    if bbox is not None and len(bbox) != 4:
        raise HTTPException(status_code=400, detail="bbox 必须是 [west, south, east, north] 四元组")
    _require_heavy_quota(user_id)

    out = _user_scene_dir(user_id, key) / "scene.tif"
    if not out.exists():
        try:
            await asyncio.to_thread(partial(compose_scene_tif, record, out, bbox=bbox))
        except SceneRasterError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except FileExistsError:
            pass
        _enforce_scene_file_cap(user_id)
    return FileResponse(
        out,
        media_type="image/tiff",
        filename=f"{record.item_id}.tif",
        headers={"Content-Disposition": f'attachment; filename="{record.item_id}.tif"'},
    )


@router.post("/{key}/import")
async def scene_import(
    key: str,
    user_id: str = Depends(require_authenticated_user),
) -> dict:
    """把场景合成为多波段 GeoTIFF 并注册进影像库（现有分析工具即可使用）。"""
    record = _get_record_or_404(user_id, key)
    _require_heavy_quota(user_id)
    try:
        result = await import_scene_as_imagery(record, user_id)
    except SceneImportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return result

"""场景 → 影像库导入服务（API 路由与 Agent 工具共用同一实现）。

合成多波段 GeoTIFF → 复用上传目录约定与归属管线登记 → 返回 imagery_id。
导入后影像对现有分析工具立即可用（波段语义来自 STAC asset key）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

from app.services.imagery_persist import _extract_metadata, _file_sha256, _persist_imagery_record
from app.agent.stac_search.raster import SceneRasterError, compose_scene_tif, render_scene_preview
from app.core.paths import imagery_root, scenes_root

logger = logging.getLogger(__name__)


class SceneImportError(Exception):
    """导入失败（远程读取或登记出错）。"""


def _user_scene_dir(user_id: str, key: str) -> Path:
    return scenes_root(create=True) / user_id / key


async def import_scene_as_imagery(record, user_id: str) -> dict:
    """把 SceneRecord 合成并注册为平台影像，返回 {imagery_id, ...}。"""
    staged = _user_scene_dir(user_id, record.key) / "scene.tif"
    compose_meta: dict = {}
    try:
        compose_meta = await asyncio.to_thread(compose_scene_tif, record, staged)
    except SceneRasterError as exc:
        raise SceneImportError(str(exc)) from exc
    except FileExistsError:
        # 复用之前的合成产物；波段语义从场景记录重建（权威来源相同）。
        compose_meta = {
            "band_roles": record.band_roles,
            "band_roles_source": "stac_assets",
            "sensor": record.satellite,
            "acquired_at": record.datetime,
        }

    imagery_id = secrets.token_hex(6)
    dest = imagery_root(create=True) / imagery_id
    try:
        (dest / "results").mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged, dest / "source.tif")
        shutil.copy2(staged, dest / "working.tif")
        from app.services.raster_preview import generate_preview
        from app.core.settings import get_settings
        try:
            await asyncio.to_thread(generate_preview, dest / "working.tif", dest / "results" / "preview.png", get_settings().agent_scene_preview_size)
        except Exception:
            logger.warning("场景预览生成失败，仅导入影像：%s", record.item_id)

        from app.services.raster_semantics import grid_context
        # 元数据复用上传管线同一份提取逻辑；波段语义以 STAC asset key 为准。
        meta = await asyncio.to_thread(_extract_metadata, dest / "working.tif")
        meta.update(await asyncio.to_thread(grid_context, dest / "working.tif"))
        meta.update(
            source_origin="stac_composition",
            native_resolution_m=record.resolution_m,
            band_roles=compose_meta.get("band_roles") or meta.get("band_roles"),
            band_roles_source="stac_assets",
            sensor=compose_meta.get("sensor") or meta.get("sensor"),
            acquired_at=compose_meta.get("acquired_at") or meta.get("acquired_at"),
            filename=f"{record.item_id}.tif",
            sha256=_file_sha256(dest / "source.tif"),
            created_at=datetime.now(timezone.utc).isoformat(),
            owner_user_id=user_id,
            preview_url=f"/api/imagery/{imagery_id}/results/preview.png" if (dest / "results" / "preview.png").exists() else None,
            working_width=meta["width"],
            working_height=meta["height"],
            compressed=False,
            compression_ratio=1.0,
            source_size_bytes=(dest / "source.tif").stat().st_size,
            working_size_bytes=(dest / "working.tif").stat().st_size,
        )
        (dest / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        await _persist_imagery_record(imagery_id, dest, meta, user_id)
    except SceneImportError:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        logger.exception("场景导入失败：%s", record.item_id)
        raise SceneImportError("场景导入失败，请稍后重试。") from exc

    return {
        "imagery_id": imagery_id,
        "item_id": record.item_id,
        "satellite": record.satellite,
        "band_roles": meta["band_roles"],
        "preview_url": meta.get("preview_url"),
        "bounds": meta.get("bounds"),
        "analysis_grid": meta.get("analysis_grid"),
        "native_resolution_m": record.resolution_m,
    }

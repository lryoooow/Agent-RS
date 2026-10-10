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
from app.agent.stac_search.raster import SceneRasterError
from app.agent.stac_search.composition_cache import (COMPOSITION_VERSION, async_file_lock, composition_directory, composition_identity, composition_lock_path, acquire_composition_lease, prune_compositions)
from app.core.paths import imagery_root

logger = logging.getLogger(__name__)


class SceneImportError(Exception):
    """导入失败（远程读取或登记出错）。"""


async def _thread_step(operation, *args, **kwargs):
    """Do not release/delete a file until its current native worker has stopped."""
    worker = asyncio.create_task(asyncio.to_thread(operation, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Cancelling to_thread only cancels its waiter, not the GDAL/file work.
        # Drain this already-started local operation, even on repeated cancellation;
        # then propagate cancellation so the caller starts no further import step.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()  # Consume a worker error; the request remains cancelled.
        raise


def _result_from_metadata(record, imagery_id: str, meta: dict) -> dict:
    return {
        "imagery_id": imagery_id,
        "item_id": record.item_id,
        "satellite": record.satellite,
        "band_roles": meta.get("band_roles") or record.band_roles,
        "preview_url": meta.get("preview_url"),
        "bounds": meta.get("bounds"),
        "analysis_grid": meta.get("analysis_grid"),
        "native_resolution_m": meta.get("native_resolution_m", record.resolution_m),
        "reused": True,
    }


def _metadata_matches(meta: dict, *, user_id: str, scene_key: str, identity: str) -> bool:
    return (
        meta.get("owner_user_id") == user_id
        and meta.get("source_scene_key") == scene_key
        and meta.get("source_origin") == "stac_composition"
        and meta.get("composition_version") == COMPOSITION_VERSION
        and meta.get("source_composition_identity") == identity
    )


def _read_cached_import(record, user_id: str, identity: str, directory: Path) -> dict | None:
    """Return an already-published import for this user and scene.

    The marker is a fast path.  The metadata scan closes the crash window where
    database publication succeeded but the marker was not written yet.
    """
    marker = directory / "import.json"
    candidates: list[str] = []
    try:
        marker_data = json.loads(marker.read_text(encoding="utf-8"))
        marker_id = str(marker_data.get("imagery_id") or "")
        if marker_id:
            candidates.append(marker_id)
    except (FileNotFoundError, OSError, ValueError, TypeError):
        pass

    root = imagery_root(create=True)
    for directory in root.iterdir():
        if directory.is_dir() and directory.name not in candidates:
            candidates.append(directory.name)

    for imagery_id in candidates:
        meta_path = root / imagery_id / "metadata.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError, TypeError):
            continue
        if _metadata_matches(meta, user_id=user_id, scene_key=record.key, identity=identity):
            if meta.get("band_roles") != record.band_roles:
                continue
            if record.quality_assets and (not meta.get("quality_mask") or not (root / imagery_id / "quality.tif").is_file()):
                continue
            return _result_from_metadata(record, imagery_id, meta)
    return None


def _write_import_marker(record, user_id: str, imagery_id: str, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "import.json"
    pending = directory / "import.json.pending"
    pending.write_text(
        json.dumps({"imagery_id": imagery_id, "scene_key": record.key}, ensure_ascii=False),
        encoding="utf-8",
    )
    pending.replace(marker)


async def _import_scene_as_imagery(record, user_id: str, *, bbox: list[float] | None = None) -> dict:
    """把 SceneRecord 合成并注册为平台影像；同一用户重复导入同一场景时复用结果。"""
    try:
        identity, spec = composition_identity(record, user_id, bbox)
        directory = composition_directory(record, user_id, bbox)
    except (ValueError, SceneRasterError) as exc:
        raise SceneImportError(str(exc)) from exc
    async with async_file_lock(composition_lock_path(user_id,identity,importing=True)):
        cached = await _thread_step(_read_cached_import, record, user_id, identity, directory)
        if cached is not None:
            return cached
        try:
            lease = await acquire_composition_lease(record, user_id, spec["bbox"])
            staged, compose_meta = lease.path, lease.metadata
        except SceneRasterError as exc:
            raise SceneImportError(str(exc)) from exc

        imagery_id = secrets.token_hex(6)
        dest = imagery_root(create=True) / imagery_id
        published = False
        directory_created = False
        try:
            dest.mkdir(exist_ok=False)
            directory_created = True
            (dest / "results").mkdir()
            shutil.copy2(staged, dest / "source.tif")
            shutil.copy2(staged, dest / "working.tif")
            if compose_meta.get("quality_mask"):
                shutil.copy2(staged.parent / "quality.tif", dest / "quality.tif")
            from app.services.raster_preview import generate_preview
            from app.core.settings import get_settings
            try:
                await _thread_step(
                    generate_preview,
                    dest / "working.tif",
                    dest / "results" / "preview.png",
                    get_settings().agent_scene_preview_size,
                )
            except Exception:
                logger.warning("场景预览生成失败，仅导入影像：%s", record.item_id)

            from app.services.raster_semantics import grid_context
            meta = await _thread_step(_extract_metadata, dest / "working.tif")
            meta.update(await _thread_step(grid_context, dest / "working.tif"))
            meta.update(
                composition_version=COMPOSITION_VERSION,
                source_composition_identity=identity,
                requested_bbox=spec["bbox"],
                quality_mask=compose_meta.get("quality_mask"),
                band_calibration=compose_meta.get("band_calibration") or meta.get("band_calibration"),
                source_origin="stac_composition",
                source_scene_key=record.key,
                source_item_id=record.item_id,
                native_resolution_m=record.resolution_m,
                band_roles=compose_meta.get("band_roles") or meta.get("band_roles"),
                band_roles_source="stac_assets",
                sensor=compose_meta.get("sensor") or meta.get("sensor"),
                acquired_at=compose_meta.get("acquired_at") or meta.get("acquired_at"),
                filename=f"{record.item_id}.tif",
                sha256=_file_sha256(dest / "source.tif"),
                created_at=datetime.now(timezone.utc).isoformat(),
                owner_user_id=user_id,
                preview_url=(
                    f"/api/imagery/{imagery_id}/results/preview.png"
                    if (dest / "results" / "preview.png").exists()
                    else None
                ),
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
            published = True
            try:
                await _thread_step(_write_import_marker, record, user_id, imagery_id, directory)
                await _thread_step(prune_compositions, user_id, protected=directory)
            except (OSError, SceneRasterError):
                logger.warning("影像已发布，缓存标记或清理失败；可按已发布元数据恢复：%s", imagery_id)
        except BaseException as exc:
            await lease.release()
            if not published and directory_created and not getattr(exc, "preserve_local_directory", False):
                root = imagery_root().resolve()
                if dest.resolve().is_relative_to(root) and dest.resolve() != root and not dest.is_symlink():
                    shutil.rmtree(dest, ignore_errors=True)
            if not isinstance(exc, Exception):
                raise
            if isinstance(exc, SceneImportError):
                raise
            logger.exception("场景导入失败：%s", record.item_id)
            raise SceneImportError("场景导入失败，请稍后重试。") from exc
        await lease.release()
        result = _result_from_metadata(record, imagery_id, meta)
        result["reused"] = False
        return result


async def import_scene_as_imagery(record, user_id: str, *, bbox: list[float] | None = None) -> dict:
    try:
        return await _import_scene_as_imagery(record, user_id, bbox=bbox)
    except SceneRasterError as exc:
        raise SceneImportError(str(exc)) from exc
    except OSError as exc:
        raise SceneImportError("场景缓存存储不可用，未完成导入。") from exc

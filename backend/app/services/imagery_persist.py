"""影像持久化服务（从 HTTP 路由层下沉，P4.5 层级修复①）。

路由与场景导入器（stac_search/importer）共同使用；此前寄生在
routes/imagery.py 里，造成 agent 服务层向上依赖 HTTP 层的倒置。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from uuid import uuid4
import logging
from pathlib import Path
from typing import Any

from app.api.errors import api_error
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool
from app.storage.object_store import get_object_store
from app.db.errors import is_missing_schema_error
from app.db.repositories._pg.imagery import (
    ImageryOwnershipConflict,
    delete_imagery as db_delete_imagery,
    insert_imagery as db_insert_imagery,
    get_imagery as db_get_imagery,
)

logger = logging.getLogger(__name__)


# 波段角色匹配关键词。顺序有讲究：更具体的角色（swir/nir）必须在宽泛角色（red）之前，
# 否则 "Near Infrared (NIR)" 会先被 "red" 里的字符误伤（"infrared" 含 "red"）。
# 中文同理："近红外"/"短波红外" 先于 "红"。
_BAND_ROLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("swir1", ("swir1", "swir 1", "swir_1", "swir-1", "swir16", "shortwave infrared 1", "短波红外1", "短波红外 1")),
    ("swir2", ("swir2", "swir 2", "swir_2", "swir-2", "swir22", "shortwave infrared 2", "短波红外2", "短波红外 2")),
    ("swir", ("swir", "shortwave infrared", "short-wave infrared", "短波红外")),
    ("nir", ("nir", "near infrared", "near-infrared", "近红外")),
    ("rededge", ("red edge", "rededge", "红边")),  # 无对应工具参数，识别出来仅用于排除
    ("green", ("green", "绿")),
    ("blue", ("blue", "蓝")),
    ("red", ("red", "红")),
)

# 元数据标签里可能携带传感器/拍摄时间的键（大小写不敏感）。
_SENSOR_TAG_KEYS = ("sensor_id", "sensor", "satellite", "satelliteid", "spacecraft_id", "platform")
_ACQUIRED_TAG_KEYS = ("tifftag_datetime", "acquisitiondate", "acquisition_date", "imaging_date", "date")


def _match_band_role(description: str) -> str | None:
    """从单条波段描述里识别光谱角色；识别不了返回 None。

    匹配到 red edge 这类无参数对应的角色时返回 'rededge'，由调用方跳过，
    避免 "Red Edge" 被 'red' 规则误认成红光波段。
    """
    text = description.strip().lower()
    if not text:
        return None
    for role, keywords in _BAND_ROLE_PATTERNS:
        for keyword in keywords:
            if keyword in text:
                return role
    return None


def _derive_band_roles(
    count: int, descriptions: list[str | None], colorinterp: list[str] | None = None, sensor: str | None = None
) -> tuple[dict[str, int], str] | tuple[None, None]:
    """波段角色表：文件自带描述优先，识别不出再按位置约定兜底。

    返回 (roles, source)。source 告诉清单消费方这份映射的置信度：
    - "descriptions"：来自文件的波段描述（可信）
    - "colorinterp"：来自 GeoTIFF 的 RGB 颜色解释；Alpha 不是光谱波段
    - "positional_gf2"：仅明确 GF-2 传感器时按 B1蓝/B2绿/B3红/B4近红外
    - 未标注传感器的多波段文件不凭数量猜测 NIR/SWIR
    - "positional_rgb"：三波段按自然 RGB 序（band1=R）
    - "positional_gray"：单波段全色

    同一角色出现在多个波段时不选择第一个；该角色留作歧义，由执行层拒绝。
    """
    roles: dict[str, int] = {}
    ambiguous: set[str] = set()
    for index, description in enumerate(descriptions or [], start=1):
        if not description:
            continue
        role = _match_band_role(str(description))
        if role and role != "rededge":
            if role in roles:
                ambiguous.add(role)
            else:
                roles[role] = index
    if roles:
        return {role: index for role, index in roles.items() if role not in ambiguous}, "descriptions"

    colors = {name: index for index, name in enumerate(colorinterp or [], start=1) if name in {"red", "green", "blue"}}
    if colors:
        return colors, "colorinterp"
    if count == 4 and colorinterp and colorinterp[-1] == "alpha":
        return {"red": 1, "green": 2, "blue": 3}, "positional_rgba"
    if count >= 4 and (sensor or "").upper().replace("-", "") in {"GF2", "GF02"}:
        return {"blue": 1, "green": 2, "red": 3, "nir": 4}, "positional_gf2"
    if count >= 4:
        return None, None
    if count == 3:
        return {"red": 1, "green": 2, "blue": 3}, "positional_rgb"
    if count == 1:
        return {"red": 1}, "positional_gray"
    return None, None



def _sensor_from_tags(tags: dict[str, str]) -> str | None:
    for key in _SENSOR_TAG_KEYS:
        value = tags.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return None



def _acquired_from_tags(tags: dict[str, str]) -> str | None:
    for key in _ACQUIRED_TAG_KEYS:
        value = tags.get(key)
        if value and str(value).strip():
            return str(value).strip()
    return None



def _display_bounds(crs: Any, bounds: Any) -> list[float] | None:
    if not crs or not bounds:
        return None
    try:
        from rasterio.crs import CRS
        from rasterio.warp import transform_bounds

        src_crs = CRS.from_user_input(crs)
        if src_crs.to_epsg() == 4326:
            return list(bounds)
        return list(transform_bounds(src_crs, CRS.from_epsg(4326), *bounds))
    except Exception:
        logger.warning("Failed to transform imagery bounds to EPSG:4326.", exc_info=True)
        return list(bounds)



def _extract_metadata(tif_path: Path) -> dict[str, Any]:
    import rasterio

    with rasterio.open(tif_path) as src:
        descriptions = list(src.descriptions or [])
        # 键统一小写：GDAL 标签键大小写不稳定（SENSOR_ID/sensor_id 都见过）。
        tags = {str(k).lower(): str(v) for k, v in (src.tags() or {}).items()}
        colorinterp = [color.name for color in src.colorinterp]
        band_roles, band_roles_source = _derive_band_roles(src.count, descriptions, colorinterp, _sensor_from_tags(tags))
        role_candidates: dict[str, list[int]] = {}
        for index, description in enumerate(descriptions, 1):
            role = _match_band_role(description or "")
            if role and role != "rededge":
                role_candidates.setdefault(role, []).append(index)
        normalized_descriptions = [str(d) if d else None for d in descriptions]
        meta = {
            "crs": str(src.crs) if src.crs else None,
            "bounds": _display_bounds(src.crs, src.bounds),
            "width": src.width,
            "height": src.height,
            "band_count": src.count,
            "pixel_size": list(src.res),
            "dtype": src.dtypes[0],
            # 波段语义：模型选 red_band/nir_band 等参数时以这份映射为准，
            # 取代散落在提示词里的「GF-2 默认波序」硬编码假设。
            # 全空的描述列表（rasterio 未写 band description 时返回 None 元组）
            # 归一成 None，让消费方不必区分"没有"和"全是空"。
            "band_descriptions": normalized_descriptions if any(normalized_descriptions) else None,
            "color_interpretations": colorinterp,
            "alpha_bands": [i for i, name in enumerate(colorinterp, 1) if name == "alpha"],
            "band_role_conflicts": {role: indexes for role, indexes in role_candidates.items() if len(indexes) > 1},
            "band_roles": band_roles,
            "band_roles_source": band_roles_source,
            "band_calibration": {str(index): {"scale": src.scales[index - 1],
                "offset": src.offsets[index - 1], "unit": src.units[index - 1],
                "tags": {key: value for key, value in src.tags(index).items() if key.upper().startswith("REFL_")}}
                for index in src.indexes},
            "sensor": _sensor_from_tags(tags),
            "acquired_at": _acquired_from_tags(tags),
        }
        return meta



def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()



async def _settle_active_task(task: asyncio.Task) -> None:
    """Drain one protected operation; repeated caller cancellation must not orphan its SDK thread."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    # Retrieve the outcome even on the cancellation path (no unobserved task exception).
    try:
        task.result()
    except (asyncio.CancelledError, Exception):
        pass


async def await_settled_operation(operation):
    """Keep an in-flight file/SDK operation alive until its actual completion before propagating cancel.

    Does not start any follow-up work. A synchronous SDK call is bounded by the
    SDK's network timeout, not by caller cancellation; source files must remain
    available until this function returns/raises.
    """
    task = asyncio.create_task(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await _settle_active_task(task)
        raise


async def _confirm_registration(pool, imagery_id: str, owner_user_id: str, attempt_id: str) -> bool | None:
    """A lost DB acknowledgement is not proof that INSERT failed or succeeded."""
    try:
        async with pool.acquire() as conn:
            row = await db_get_imagery(conn, imagery_id=imagery_id)
        return bool(row and str(row["owner_user_id"]) == owner_user_id
                    and (row.get("metadata") or {}).get("_persistence_attempt_id") == attempt_id)
    except Exception:
        logger.exception("Unable to confirm imagery registration attempt: %s", imagery_id)
        return None


def _retain_pending_cleanup(dest_dir, *, imagery_id, owner_user_id, attempt_id, backend, owned_keys, pending_steps):
    """Keep this invocation's evidence outside every public imagery-ID directory.

    This private folder is not a retry worker. An operator can retry the listed
    exact keys and nonce-guarded row deletion without touching previous uploads.
    """
    root = dest_dir.parent.resolve()
    private = root / ".imagery-cleanup-pending"
    if private.is_symlink() or not private.resolve().is_relative_to(root):
        raise OSError("Unsafe cleanup record directory")
    private.mkdir(mode=0o700, exist_ok=True)
    task_dir = private / attempt_id
    task_dir.mkdir(mode=0o700, exist_ok=False)
    retained = dest_dir
    if dest_dir.exists():
        if dest_dir.is_symlink() or dest_dir.resolve().parent != root:
            raise OSError("Unsafe pending imagery directory")
        retained = task_dir / "image"
        dest_dir.rename(retained)
    record = {"schema_version": 1, "state": "cleanup_pending", "attempt_id": attempt_id,
              "imagery_id": imagery_id, "owner_user_id": owner_user_id, "storage_backend": backend,
              "object_keys": list(owned_keys), "pending_steps": list(pending_steps),
              "local_directory": str(retained)}
    temporary = task_dir / "cleanup.json.pending"
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(task_dir / "cleanup.json")
    logger.error("Imagery cleanup pending; private record retained: %s", task_dir)


async def _rollback_minio_persist(pool, store, imagery_id: str, owner_user_id: str,
                                  *, owned_keys: list[str], attempt_id: str) -> list[str]:
    """Report incomplete steps; exact keys and a row nonce constrain compensation."""
    pending = []
    # The row may have changed since reservation. Do not delete objects now
    # belonging to a newer registration, even when the owner ID is unchanged.
    if await _confirm_registration(pool, imagery_id, owner_user_id, attempt_id) is not True:
        return ["confirm_resource_ownership"]
    if owned_keys:
        try:
            if store is None:
                raise RuntimeError("Object store unavailable for compensation")
            await store.delete_keys(owned_keys)
        except Exception:
            pending.append("delete_objects")
            logger.exception("Unable to delete this upload's objects: %s", imagery_id)
    try:
        async with pool.acquire() as conn:
            deleted = await db_delete_imagery(conn, imagery_id=imagery_id, owner_user_id=owner_user_id,
                                             persistence_attempt_id=attempt_id)
        if not deleted and await _confirm_registration(pool, imagery_id, owner_user_id, attempt_id) is not False:
            pending.append("delete_db_row")
    except Exception:
        pending.append("delete_db_row")
        logger.exception("Unable to delete this registration's DB row: %s", imagery_id)
    return pending


async def _finish_failed_registration(pool, store, dest_dir, *, imagery_id, owner_user_id,
                                      attempt_id, backend, row_created, registration_attempted, owned_keys):
    confirmed = True if row_created else (
        await _confirm_registration(pool, imagery_id, owner_user_id, attempt_id)
        if registration_attempted else False)
    pending = []
    if confirmed is None:
        pending = ["confirm_registration"]
    elif confirmed:
        pending = await _rollback_minio_persist(pool, store, imagery_id, owner_user_id,
                                               owned_keys=owned_keys, attempt_id=attempt_id)
    if pending:
        try:
            await asyncio.to_thread(_retain_pending_cleanup, dest_dir, imagery_id=imagery_id,
                owner_user_id=owner_user_id, attempt_id=attempt_id, backend=backend,
                owned_keys=owned_keys, pending_steps=pending)
        except Exception:
            # If moving/writing failed, callers must not discard the only input/evidence.
            logger.exception("Unable to retain cleanup record; preserve local imagery: %s", dest_dir)
    return pending, bool(pending and dest_dir.exists())


async def _persist_imagery_record(imagery_id: str, dest_dir: Path, meta: dict[str, Any], owner_user_id: str) -> None:
    """Create a new image; cancellation settles active I/O before owned compensation."""
    backend = get_settings().storage_backend.strip().lower()
    if backend != "minio":
        await _persist_db_record_best_effort(imagery_id, meta, owner_user_id, backend, dest_dir=dest_dir)
        return
    pool = await fetch_optional_pool()
    if pool is None:
        raise api_error(503, "SERVICE_UNAVAILABLE", "对象存储模式需要数据库，但数据库当前不可用。")
    attempt_id = uuid4().hex
    persisted_meta = {**meta, "_persistence_attempt_id": attempt_id}
    row_created = registration_attempted = False
    owned_keys: list[str] = []
    store = None

    async def register():
        nonlocal row_created, registration_attempted
        async with pool.acquire() as conn:
            registration_attempted = True
            await db_insert_imagery(conn, imagery_id=imagery_id, owner_user_id=owner_user_id,
                filename=meta.get("filename"), sha256=meta.get("sha256"), bounds=meta.get("bounds"),
                bands=meta.get("band_count"), storage_backend=backend, metadata=persisted_meta, create_only=True)
            row_created = True

    try:
        await await_settled_operation(register())
        store = get_object_store()
        for rel in ("source.tif", "working.tif", "quality.tif", "metadata.json", "results/preview.png"):
            local = dest_dir / rel
            if not local.exists():
                continue
            key = f"{imagery_id}/{rel}"
            if await await_settled_operation(store.exists(key)):
                raise api_error(409, "CONFLICT", "影像对象已存在，请重试上传。")
            owned_keys.append(key)
            await await_settled_operation(store.put(key, local))
    except BaseException as exc:
        pending, retain_local = [], False
        if not isinstance(exc, ImageryOwnershipConflict):
            cleanup = asyncio.create_task(_finish_failed_registration(pool, store, dest_dir,
                imagery_id=imagery_id, owner_user_id=owner_user_id, attempt_id=attempt_id, backend=backend,
                row_created=row_created, registration_attempted=registration_attempted, owned_keys=owned_keys))
            await _settle_active_task(cleanup)
            pending, retain_local = cleanup.result()
        if isinstance(exc, asyncio.CancelledError):
            exc.preserve_local_directory = retain_local
            raise
        if isinstance(exc, ImageryOwnershipConflict):
            raise api_error(409, "CONFLICT", "影像 ID 冲突，请重试上传。") from exc
        from fastapi import HTTPException
        if pending:
            failure = api_error(503 if not row_created else 502, "IMAGERY_CLEANUP_PENDING",
                                "影像保存失败，清理尚未完成，已保留诊断线索。")
            failure.preserve_local_directory = retain_local
            raise failure from exc
        if isinstance(exc, HTTPException):
            raise
        if not isinstance(exc, Exception):
            raise
        logger.exception("Imagery registration/upload failed; owned compensation finished: %s", imagery_id)
        if not row_created:
            raise api_error(503, "SERVICE_UNAVAILABLE", "影像登记失败，请稍后重试。") from exc
        raise api_error(502, "UPSTREAM_FAILED", "影像上传到对象存储失败，请重试。") from exc


async def _persist_db_record_best_effort(imagery_id, meta, owner_user_id, backend, *, dest_dir):
    """Keep local no-DB compatibility, but refuse an existing DB image ID."""
    pool = await fetch_optional_pool()
    if pool is None:
        return
    attempt_id = uuid4().hex
    row_created = registration_attempted = False

    async def register():
        nonlocal row_created, registration_attempted
        async with pool.acquire() as conn:
            registration_attempted = True
            await db_insert_imagery(conn, imagery_id=imagery_id, owner_user_id=owner_user_id,
                filename=meta.get("filename"), sha256=meta.get("sha256"), bounds=meta.get("bounds"),
                bands=meta.get("band_count"), storage_backend=backend,
                metadata={**meta, "_persistence_attempt_id": attempt_id}, create_only=True)
            row_created = True

    try:
        await await_settled_operation(register())
    except asyncio.CancelledError as exc:
        cleanup = asyncio.create_task(_finish_failed_registration(pool, None, dest_dir,
            imagery_id=imagery_id, owner_user_id=owner_user_id, attempt_id=attempt_id, backend=backend,
            row_created=row_created, registration_attempted=registration_attempted, owned_keys=[]))
        await _settle_active_task(cleanup)
        _, exc.preserve_local_directory = cleanup.result()
        raise
    except ImageryOwnershipConflict as exc:
        raise api_error(409, "CONFLICT", "影像 ID 已存在，请重试上传。") from exc
    except Exception as exc:
        if is_missing_schema_error(exc):
            logger.warning("imagery 表未建，使用本地 metadata.json 归属：%s", imagery_id)
        else:
            logger.exception("本地影像 DB 登记失败，保留 metadata.json 归属：%s", imagery_id)

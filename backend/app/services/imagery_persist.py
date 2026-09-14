"""影像持久化服务（从 HTTP 路由层下沉，P4.5 层级修复①）。

路由与场景导入器（stac_search/importer）共同使用；此前寄生在
routes/imagery.py 里，造成 agent 服务层向上依赖 HTTP 层的倒置。
"""

from __future__ import annotations

import hashlib
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
)

logger = logging.getLogger(__name__)


# 波段角色匹配关键词。顺序有讲究：更具体的角色（swir/nir）必须在宽泛角色（red）之前，
# 否则 "Near Infrared (NIR)" 会先被 "red" 里的字符误伤（"infrared" 含 "red"）。
# 中文同理："近红外"/"短波红外" 先于 "红"。
_BAND_ROLE_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
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
    count: int, descriptions: list[str | None]
) -> tuple[dict[str, int], str] | tuple[None, None]:
    """波段角色表：文件自带描述优先，识别不出再按位置约定兜底。

    返回 (roles, source)。source 告诉清单消费方这份映射的置信度：
    - "descriptions"：来自文件的波段描述（可信）
    - "positional_gf2"：无描述时按 GF-2 波序约定 B1蓝/B2绿/B3红/B4近红外/B5短波红外
    - "positional_rgb"：三波段按自然 RGB 序（band1=R）
    - "positional_gray"：单波段全色

    同一角色出现在多个波段时取第一个（如 Sentinel-2 的多个 red edge 只会丢给
    rededge 排除项，不影响 red 本体）。
    """
    roles: dict[str, int] = {}
    for index, description in enumerate(descriptions or [], start=1):
        if not description:
            continue
        role = _match_band_role(str(description))
        if role and role != "rededge" and role not in roles:
            roles[role] = index
    if roles:
        return roles, "descriptions"

    if count >= 4:
        roles = {"blue": 1, "green": 2, "red": 3, "nir": 4}
        if count >= 5:
            roles["swir"] = 5
        return roles, "positional_gf2"
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
        band_roles, band_roles_source = _derive_band_roles(src.count, descriptions)
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
            "band_roles": band_roles,
            "band_roles_source": band_roles_source,
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



async def _persist_imagery_record(
    imagery_id: str,
    dest_dir: Path,
    meta: dict[str, Any],
    owner_user_id: str,
) -> None:
    """上传后持久化：DB 登记影像归属 + minio 后端上传二进制到对象存储。

    后端语义差异（#2 根因修复）：
    - local 后端：DB 登记 best-effort（无库/表未建/冲突只告警，本地 metadata.json 兜底）；不上传对象。
    - minio 后端：DB owner 行是硬依赖——跨实例的 owner 鉴权 / list / read 全靠它。故：
        ① DB 不可用 → 直接 503，不产生任何孤儿对象；
        ② DB-first（先写 DB 行，再传对象）：任一步失败都回滚已写的 DB 行 + 已传对象，
           保证"DB 行与对象要么都在、要么都不在"，杜绝"对象在/DB 无行"的孤儿对象。
    raises HTTPException：minio 模式下 DB 不可用/写入失败/对象上传失败。
    """
    settings = get_settings()
    backend = settings.storage_backend.strip().lower()

    if backend != "minio":
        await _persist_db_record_best_effort(imagery_id, meta, owner_user_id, backend)
        return

    # ── minio 后端：DB 硬依赖 + DB-first + 失败回滚 ──
    pool = await fetch_optional_pool()
    if pool is None:
        raise api_error(503, "SERVICE_UNAVAILABLE", "对象存储模式需要数据库，但数据库当前不可用。")
    # ① 先写 DB owner 行（此时未传任何对象，失败即抛、无对象需清理）。
    try:
        async with pool.acquire() as conn:
            await db_insert_imagery(
                conn,
                imagery_id=imagery_id,
                owner_user_id=owner_user_id,
                filename=meta.get("filename"),
                sha256=meta.get("sha256"),
                bounds=meta.get("bounds"),
                bands=meta.get("band_count"),
                storage_backend=backend,
                metadata=meta,
            )
    except ImageryOwnershipConflict as exc:
        raise api_error(409, "CONFLICT", "影像 ID 冲突，请重试上传。") from exc
    except Exception as exc:
        logger.exception("影像 DB 登记失败（minio 模式，拒绝上传以防孤儿对象）：%s", imagery_id)
        raise api_error(503, "SERVICE_UNAVAILABLE", "影像登记失败，请稍后重试。") from exc

    # ② 上传对象（失败则回滚 DB 行 + 清已传对象，保持原子性）。
    store = get_object_store()
    try:
        for rel in ("source.tif", "working.tif", "metadata.json", "results/preview.png"):
            local = dest_dir / rel
            if local.exists():
                await store.put(f"{imagery_id}/{rel}", local)
    except Exception as exc:
        logger.exception("影像对象上传失败，回滚 DB 行与已传对象：%s", imagery_id)
        await _rollback_minio_persist(pool, store, imagery_id, owner_user_id)
        raise api_error(502, "UPSTREAM_FAILED", "影像上传到对象存储失败，请重试。") from exc


async def _persist_db_record_best_effort(
    imagery_id: str, meta: dict[str, Any], owner_user_id: str, backend: str
) -> None:
    """local 后端的 DB 登记：尽力而为，无库/表未建/冲突只告警，绝不阻断上传（与迁移前一致）。"""
    pool = await fetch_optional_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await db_insert_imagery(
                conn,
                imagery_id=imagery_id,
                owner_user_id=owner_user_id,
                filename=meta.get("filename"),
                sha256=meta.get("sha256"),
                bounds=meta.get("bounds"),
                bands=meta.get("band_count"),
                storage_backend=backend,
                metadata=meta,
            )
    except ImageryOwnershipConflict:
        logger.warning("影像 ID 已属他人，跳过 DB 登记（local metadata.json 兜底）：%s", imagery_id)
    except Exception as exc:
        if is_missing_schema_error(exc):
            logger.warning("imagery 表未建，跳过 DB 登记（本地 metadata.json 兜底）：%s", imagery_id)
        else:
            logger.exception("影像 DB 登记失败（不阻断上传）：%s", imagery_id)


async def _rollback_minio_persist(pool, store, imagery_id: str, owner_user_id: str) -> None:
    """minio 上传失败的回滚：删已传对象 + 删 DB 行（best-effort，不掩盖原始错误）。"""
    try:
        await store.delete_prefix(imagery_id)
    except Exception:
        logger.exception("回滚：删除已上传对象失败：%s", imagery_id)
    try:
        async with pool.acquire() as conn:
            await db_delete_imagery(conn, imagery_id=imagery_id, owner_user_id=owner_user_id)
    except Exception:
        logger.exception("回滚：删除 DB 行失败：%s", imagery_id)


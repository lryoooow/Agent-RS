from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.auth.current_user import get_current_user_id
from app.core.paths import imagery_root
from app.core.settings import get_settings
from app.db.errors import is_missing_schema_error
from app.db.pool import fetch_optional_pool
from app.db.repositories.imagery import (
    delete_imagery as db_delete_imagery,
    get_imagery as db_get_imagery,
    insert_imagery as db_insert_imagery,
    list_imagery as db_list_imagery,
)
from app.db.repositories._pg.imagery import ImageryOwnershipConflict
from app.storage.object_store import get_object_store, object_store_for

router = APIRouter(prefix="/imagery", tags=["imagery"])
logger = logging.getLogger(__name__)

IMAGERY_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")


class ImageryMetadata(BaseModel):
    imagery_id: str
    filename: str
    crs: str | None = None
    bounds: list[float] | None = None
    width: int = 0
    height: int = 0
    band_count: int = 0
    pixel_size: list[float] | None = None
    dtype: str = ""
    preview_url: str | None = None
    working_width: int = 0
    working_height: int = 0
    compressed: bool = False
    compression_ratio: float | None = None
    sha256: str | None = None
    created_at: str | None = None
    source_size_bytes: int | None = None
    working_size_bytes: int | None = None


class CleanupResult(BaseModel):
    removed: list[str]


class DeleteResult(BaseModel):
    imagery_id: str
    deleted: bool


def _imagery_root() -> Path:
    return imagery_root(create=True)


def _imagery_dir(imagery_id: str) -> Path:
    if not IMAGERY_ID_PATTERN.fullmatch(imagery_id):
        raise HTTPException(status_code=400, detail="非法影像 ID")
    return _imagery_root() / imagery_id


def _safe_result_path(imagery_id: str, filename: str) -> Path:
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    results_root = (_imagery_dir(imagery_id) / "results").resolve()
    result_path = (results_root / filename).resolve()
    try:
        result_path.relative_to(results_root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="非法文件路径") from exc
    return result_path


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove file: %s", path, exc_info=True)


def _safe_rmtree(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        logger.warning("Failed to remove directory: %s", path, exc_info=True)


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
        return {
            "crs": str(src.crs) if src.crs else None,
            "bounds": _display_bounds(src.crs, src.bounds),
            "width": src.width,
            "height": src.height,
            "band_count": src.count,
            "pixel_size": list(src.res),
            "dtype": src.dtypes[0],
        }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rescaled_shape(width: int, height: int, max_dimension: int) -> tuple[int, int, bool]:
    longest = max(width, height)
    if longest <= max_dimension:
        return width, height, False
    scale = max_dimension / longest
    return max(1, int(round(width * scale))), max(1, int(round(height * scale))), True


def _create_working_tif(source_path: Path, working_path: Path, settings) -> dict[str, Any]:
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling

    with rasterio.open(source_path) as src:
        working_width, working_height, resampled = _rescaled_shape(
            src.width,
            src.height,
            settings.imagery_working_max_dimension,
        )
        data = src.read(
            out_shape=(src.count, working_height, working_width),
            resampling=Resampling.bilinear if resampled else Resampling.nearest,
        )
        transform = src.transform * src.transform.scale(
            src.width / working_width,
            src.height / working_height,
        )
        profile = src.profile.copy()
        profile.update(
            width=working_width,
            height=working_height,
            transform=transform,
            tiled=True,
            blockxsize=512,
            blockysize=512,
            compress=settings.imagery_compression,
        )
        dtype = np.dtype(profile["dtype"])
        if np.issubdtype(dtype, np.integer):
            profile["predictor"] = 2
        elif np.issubdtype(dtype, np.floating):
            profile["predictor"] = 3

    with rasterio.open(working_path, "w", **profile) as dst:
        dst.write(data)

    source_size = source_path.stat().st_size
    working_size = working_path.stat().st_size
    return {
        "working_width": working_width,
        "working_height": working_height,
        "compressed": bool(resampled or working_size < source_size),
        "compression_ratio": round(working_size / source_size, 4) if source_size else None,
        "source_size_bytes": source_size,
        "working_size_bytes": working_size,
    }


def _stretch_to_byte(values):
    import numpy as np

    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros(values.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [2, 98])
    if high <= low:
        return np.zeros(values.shape, dtype=np.uint8)
    scaled = (values - low) / (high - low)
    return (np.clip(scaled, 0, 1) * 255).astype(np.uint8)


def _generate_preview(source_path: Path, output_path: Path, max_dimension: int) -> None:
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.enums import Resampling

    with rasterio.open(source_path) as src:
        preview_width, preview_height, _ = _rescaled_shape(
            src.width,
            src.height,
            max_dimension,
        )
        if src.count >= 4:
            bands = [3, 2, 1]
        elif src.count >= 3:
            bands = [1, 2, 3]
        else:
            bands = [1]
        data = src.read(
            bands,
            out_shape=(len(bands), preview_height, preview_width),
            resampling=Resampling.bilinear,
        ).astype(np.float32)

    if len(bands) == 1:
        gray = _stretch_to_byte(data[0])
        image = Image.fromarray(gray, mode="L").convert("RGBA")
    else:
        rgb = np.dstack([_stretch_to_byte(channel) for channel in data[:3]])
        image = Image.fromarray(rgb, mode="RGB").convert("RGBA")
    image.save(output_path, optimize=True)


async def _write_upload_to_temp(file: UploadFile, max_bytes: int, suffix: str) -> Path:
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    temp_path = Path(temp_file.name)
    temp_file.close()
    total_bytes = 0
    try:
        with open(temp_path, "wb") as target:
            while chunk := await file.read(1024 * 1024):
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(status_code=413, detail="文件超过大小限制")
                target.write(chunk)
    except Exception:
        _safe_unlink(temp_path)
        raise
    return temp_path


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def _read_metadata(meta_file: Path) -> dict[str, Any] | None:
    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("Invalid imagery metadata skipped: %s", meta_file, exc_info=True)
        return None


def _metadata_response(entry: Path, meta: dict[str, Any]) -> ImageryMetadata:
    filename = str(meta.get("filename") or meta.get("original_filename") or "source.tif")
    payload = {key: value for key, value in meta.items() if key != "filename"}
    return ImageryMetadata(imagery_id=entry.name, filename=filename, **payload)


def _metadata_owner(meta: dict[str, Any]) -> str:
    return str(meta.get("owner_user_id") or get_settings().default_user_id)


async def _db_imagery_owner(imagery_id: str) -> str | None:
    """查 DB 取该影像 owner（不限归属）。DB 不可用/表未建/无此行 → None（交由 json 兜底）。"""
    pool = await fetch_optional_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            row = await db_get_imagery(conn, imagery_id=imagery_id)
    except Exception as exc:
        if not is_missing_schema_error(exc):
            logger.exception("影像 owner DB 查询失败：%s", imagery_id)
        return None
    return row["owner_user_id"] if row else None


async def _effective_backend(imagery_id: str) -> str:
    """该影像二进制实际所在后端（per-row 路由，#3 根因修复）。

    以 DB 行的 storage_backend 列为准——全局后端切换后，老影像（写时 local）/
    新影像（写时 minio）各按自己的真实后端读/删，不被全局 settings 误导致读 404 或漏删对象。
    DB 无此行（老影像/无库/表未建）→ 'local'：迁移前的影像只在本地盘，恒为 local。
    """
    pool = await fetch_optional_pool()
    if pool is None:
        return "local"
    try:
        async with pool.acquire() as conn:
            row = await db_get_imagery(conn, imagery_id=imagery_id)
    except Exception as exc:
        if not is_missing_schema_error(exc):
            logger.exception("影像后端 DB 查询失败（回落 local）：%s", imagery_id)
        return "local"
    if not row:
        return "local"
    return str(row.get("storage_backend") or "local").strip().lower()


async def _ensure_imagery_owner_db_first(imagery_id: str, meta: dict[str, Any]) -> None:
    """owner 校验：DB 有此影像 → 以 DB owner 为准（租户隔离硬约束）；否则回落 metadata.json。"""
    db_owner = await _db_imagery_owner(imagery_id)
    owner = db_owner if db_owner is not None else _metadata_owner(meta)
    if owner != get_current_user_id():
        raise HTTPException(status_code=404, detail="Imagery was not found.")


def _read_metadata_only(dest_dir: Path) -> dict[str, Any]:
    """读 metadata.json（不校验 owner）。文件缺失/损坏 → 对应 HTTP 错误。"""
    meta_file = dest_dir / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="Imagery was not found.")
    meta = _read_metadata(meta_file)
    if meta is None:
        raise HTTPException(status_code=500, detail="Imagery metadata is invalid.")
    return meta


async def _read_owned_metadata(dest_dir: Path) -> dict[str, Any]:
    """读 metadata.json 并校验 owner（DB 优先 + json 兜底）。imagery_id 取自目录名。"""
    meta = _read_metadata_only(dest_dir)
    await _ensure_imagery_owner_db_first(dest_dir.name, meta)
    return meta


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
        raise HTTPException(status_code=503, detail="对象存储模式需要数据库，但数据库当前不可用。")
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
        raise HTTPException(status_code=409, detail="影像 ID 冲突，请重试上传。") from exc
    except Exception as exc:
        logger.exception("影像 DB 登记失败（minio 模式，拒绝上传以防孤儿对象）：%s", imagery_id)
        raise HTTPException(status_code=503, detail="影像登记失败，请稍后重试。") from exc

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
        raise HTTPException(status_code=502, detail="影像上传到对象存储失败，请重试。") from exc


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


@router.post("/upload", response_model=ImageryMetadata)
async def upload_imagery(file: UploadFile = File(...)) -> ImageryMetadata:
    settings = get_settings()
    owner_user_id = get_current_user_id()

    if not file.filename or not file.filename.lower().endswith((".tif", ".tiff")):
        raise HTTPException(status_code=400, detail="仅支持 GeoTIFF (.tif/.tiff) 格式")

    suffix = Path(file.filename).suffix.lower()
    temp_path = await _write_upload_to_temp(file, settings.imagery_max_file_bytes, suffix)
    try:
        meta = await asyncio.to_thread(_extract_metadata, temp_path)
    except Exception as exc:
        _safe_unlink(temp_path)
        logger.warning("Failed to parse uploaded GeoTIFF: %s", file.filename, exc_info=True)
        raise HTTPException(status_code=422, detail="无法解析 GeoTIFF，请确认文件格式和影像完整性") from exc

    imagery_id = uuid.uuid4().hex[:12]
    dest_dir = _imagery_dir(imagery_id)
    results_dir = dest_dir / "results"
    dest_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(exist_ok=True)

    source_path = dest_dir / "source.tif"
    working_path = dest_dir / "working.tif"
    preview_path = results_dir / "preview.png"
    try:
        await asyncio.to_thread(shutil.move, str(temp_path), source_path)
        working_meta = await asyncio.to_thread(_create_working_tif, source_path, working_path, settings)
        await asyncio.to_thread(_generate_preview, source_path, preview_path, settings.imagery_preview_max_dimension)
    except Exception as exc:
        _safe_unlink(temp_path)
        _safe_rmtree(dest_dir)
        logger.warning("Failed to process uploaded GeoTIFF: %s", file.filename, exc_info=True)
        raise HTTPException(status_code=422, detail="无法处理 GeoTIFF，请确认影像波段、尺寸和压缩格式") from exc

    meta = {
        **meta,
        **working_meta,
        "filename": file.filename,
        "preview_url": f"/api/imagery/{imagery_id}/results/preview.png",
        "sha256": await asyncio.to_thread(_file_sha256, source_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "owner_user_id": owner_user_id,
    }
    _write_json_atomic(dest_dir / "metadata.json", meta)
    try:
        await _persist_imagery_record(imagery_id, dest_dir, meta, owner_user_id)
    except HTTPException:
        # minio 模式持久化失败（DB 不可用/对象上传失败，已在内部回滚 DB 行与对象）：
        # 清掉本地已写目录，避免留下"上传成功"假象的孤儿本地目录，再把错误抛给客户端。
        _safe_rmtree(dest_dir)
        raise

    logger.info(
        "Imagery uploaded: %s, %s, %s bands, working=%sx%s",
        imagery_id,
        file.filename,
        meta["band_count"],
        meta["working_width"],
        meta["working_height"],
    )
    payload = {key: value for key, value in meta.items() if key != "filename"}
    return ImageryMetadata(imagery_id=imagery_id, filename=file.filename or "", **payload)


@router.get("", response_model=list[ImageryMetadata])
async def list_imagery() -> list[ImageryMetadata]:
    current_user_id = get_current_user_id()
    # 合并两源（DB 优先）：本地扫描覆盖老影像/无库场景，DB 覆盖新影像（含 minio 后端本地无文件）。
    # 按 imagery_id 去重，DB 同 id 覆盖本地。local 后端 + 无库时纯本地扫描，行为与迁移前一致。
    merged: dict[str, ImageryMetadata] = {}
    root = _imagery_root()
    if root.exists():
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or not IMAGERY_ID_PATTERN.fullmatch(entry.name):
                continue
            meta_file = entry / "metadata.json"
            if not meta_file.exists():
                continue
            meta = _read_metadata(meta_file)
            if meta is None:
                continue
            if _metadata_owner(meta) != current_user_id:
                continue
            merged[entry.name] = _metadata_response(entry, meta)

    pool = await fetch_optional_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                rows = await db_list_imagery(conn, owner_user_id=current_user_id)
            for row in rows:
                meta = dict(row.get("metadata") or {})
                if not meta:
                    continue
                filename = str(meta.get("filename") or "source.tif")
                payload = {k: v for k, v in meta.items() if k != "filename"}
                merged[row["imagery_id"]] = ImageryMetadata(
                    imagery_id=row["imagery_id"], filename=filename, **payload
                )
        except Exception as exc:
            if not is_missing_schema_error(exc):
                logger.exception("影像列表 DB 查询失败（回落本地扫描结果）")
    return list(merged.values())


@router.post("/cleanup", response_model=CleanupResult)
async def cleanup_imagery() -> CleanupResult:
    root = _imagery_root()
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.storage_orphan_max_age_hours)
    removed: list[str] = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        meta_file = entry / "metadata.json"
        if meta_file.exists():
            continue
        modified = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
        if modified > cutoff:
            continue
        _safe_rmtree(entry)
        removed.append(entry.name)
    return CleanupResult(removed=removed)


async def _load_owned_meta_db_first(imagery_id: str) -> dict[str, Any]:
    """读影像元数据并校验 owner，DB 优先 + 本地 metadata.json 兜底。

    minio 后端下本地可能没有 metadata.json（只在对象存储），故先查 DB 拿 meta+owner；
    DB 无此行（老影像/无库）→ 回落本地 metadata.json（原逻辑，已验证）。
    """
    pool = await fetch_optional_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                row = await db_get_imagery(conn, imagery_id=imagery_id)
        except Exception as exc:
            if not is_missing_schema_error(exc):
                logger.exception("影像元数据 DB 查询失败：%s", imagery_id)
            row = None
        if row is not None:
            if row["owner_user_id"] != get_current_user_id():
                raise HTTPException(status_code=404, detail="Imagery was not found.")
            meta = dict(row.get("metadata") or {})
            if meta:
                return meta
    # 兜底：本地 metadata.json（含 owner 校验）。
    return await _read_owned_metadata(_imagery_dir(imagery_id))


@router.get("/{imagery_id}", response_model=ImageryMetadata)
async def get_imagery(imagery_id: str) -> ImageryMetadata:
    meta = await _load_owned_meta_db_first(imagery_id)
    filename = str(meta.get("filename") or "source.tif")
    payload = {k: v for k, v in meta.items() if k != "filename"}
    return ImageryMetadata(imagery_id=imagery_id, filename=filename, **payload)


@router.delete("/{imagery_id}", response_model=DeleteResult)
async def delete_imagery(imagery_id: str) -> DeleteResult:
    dest_dir = _imagery_dir(imagery_id)
    # owner 校验（DB 优先 + json 兜底）。minio 后端本地无 metadata.json 时靠 DB 校验。
    await _ensure_owned_for_mutation(imagery_id, dest_dir)
    # per-row 路由（#3）：按该影像写入时的真实后端删对象存储，而非全局 settings。
    # 全局从 minio 切回 local 后，仍能删掉老 minio 影像的对象（不漏删）。
    if await _effective_backend(imagery_id) == "minio":
        await object_store_for("minio").delete_prefix(imagery_id)
    _safe_rmtree(dest_dir)
    pool = await fetch_optional_pool()
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await db_delete_imagery(conn, imagery_id=imagery_id, owner_user_id=get_current_user_id())
        except Exception as exc:
            if not is_missing_schema_error(exc):
                logger.exception("影像 DB 行删除失败：%s", imagery_id)
    deleted = not dest_dir.exists()
    return DeleteResult(imagery_id=imagery_id, deleted=deleted)


async def _ensure_owned_for_mutation(imagery_id: str, dest_dir: Path) -> None:
    """变更操作（删除）的 owner 校验：DB 有行用 DB，否则本地 metadata.json。

    与读路径区别：本地目录已不存在但 DB 有行（minio 后端）时，仍能据 DB 校验并放行删除。
    """
    db_owner = await _db_imagery_owner(imagery_id)
    if db_owner is not None:
        if db_owner != get_current_user_id():
            raise HTTPException(status_code=404, detail="Imagery was not found.")
        return
    # DB 无此行 → 回落本地 metadata.json（必须存在且 owner 匹配）。
    await _read_owned_metadata(dest_dir)


def _result_media_type(filename: str) -> str:
    if filename.endswith(".png"):
        return "image/png"
    if filename.endswith(".docx"):
        # 分析报告（Word）。nosniff 中间件要求 Content-Type 准确，故显式给 docx 类型。
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return "image/tiff"


@router.get("/{imagery_id}/results/{filename}")
async def get_result_file(imagery_id: str, filename: str):
    # 路径安全校验（防穿越/非法文件名），与 local 后端共用。
    result_path = _safe_result_path(imagery_id, filename)
    media_type = _result_media_type(filename)

    # per-row 路由（#3）：按该影像写入时的真实后端读，而非全局 settings。
    # 全局从 local 切到 minio（或反向）后，老影像仍按自己的后端读，不致 404。
    if await _effective_backend(imagery_id) == "minio":
        # owner 校验（DB 优先）；本地可能无文件，故不依赖本地 metadata.json。
        await _ensure_owned_for_mutation(imagery_id, _imagery_dir(imagery_id))
        store = object_store_for("minio")
        key = f"{imagery_id}/results/{filename}"
        try:
            stream = await store.open_stream(key)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="结果文件不存在")
        # 代理流式：保留 owner 鉴权（不用 presigned URL，避免绕过校验越权）。
        return StreamingResponse(
            stream,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    # local 后端：原逻辑，本地 metadata.json owner 校验 + FileResponse。
    await _read_owned_metadata(result_path.parent.parent)
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")
    return FileResponse(result_path, media_type=media_type, filename=filename)

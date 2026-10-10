from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.api.errors import api_error
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.auth.current_user import get_current_user_id
from app.uploads import UploadSizeExceeded, stream_upload_to_temp
from app.core.paths import imagery_root
from app.services.imagery_persist import (
    _extract_metadata,
    _file_sha256,
    _persist_imagery_record,
    await_settled_operation,
)
from app.core.settings import get_settings
from app.core.resource_limits import resource_semaphore
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
from app.api.deps import require_admin, require_authenticated_user
from app.agent.roi_buildings import BuildingReadiness, RoiBuildingRequest, building_readiness

router = APIRouter(prefix="/imagery", tags=["imagery"])
logger = logging.getLogger(__name__)

IMAGERY_ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")


@router.post('/roi-buildings/readiness', response_model=BuildingReadiness)
async def roi_building_readiness(request: RoiBuildingRequest, user_id: str = Depends(require_authenticated_user)):
    return await building_readiness(request, user_id=user_id)


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
    band_descriptions: list[str | None] | None = None
    band_roles: dict[str, int] | None = None
    band_roles_source: str | None = None
    color_interpretations: list[str] | None = None
    alpha_bands: list[int] | None = None
    sensor: str | None = None
    acquired_at: str | None = None
    preview_url: str | None = None
    source_origin: str | None = None
    native_resolution_m: float | None = None
    source_grid: dict[str, Any] | None = None
    analysis_grid: dict[str, Any] | None = None
    resampled: bool = False
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
        raise api_error(400, "INVALID_ID", "非法影像 ID。")
    return _imagery_root() / imagery_id


def _safe_result_path(imagery_id: str, filename: str) -> Path:
    if "/" in filename or "\\" in filename:
        raise api_error(400, "INVALID_FILENAME", "非法文件名。")
    results_root = (_imagery_dir(imagery_id) / "results").resolve()
    result_path = (results_root / filename).resolve()
    try:
        result_path.relative_to(results_root)
    except ValueError as exc:
        raise api_error(400, "INVALID_PATH", "非法文件路径。") from exc
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



def _rescaled_shape(width: int, height: int, max_dimension: int) -> tuple[int, int, bool]:
    longest = max(width, height)
    if longest <= max_dimension:
        return width, height, False
    scale = max_dimension / longest
    return max(1, int(round(width * scale))), max(1, int(round(height * scale))), True


def _validate_band_budget(meta: dict[str, Any], settings) -> None:
    """上传影像的波段数/工作图体积预算校验（G2，防多波段 OOM）→ 413。

    在 _extract_metadata 之后、_create_working_tif 之前执行：只读已提取的
    width/height/band_count/dtype 元数据（不再触盘），按与工作图同一缩放规则
    （_rescaled_shape）预估 count × 工作宽 × 工作高 × itemsize，超限即拒。
    防复发：新增影像处理入口若绕过本路由，必须复用本校验。
    """
    import numpy as np

    band_count = int(meta.get("band_count") or 0)
    if band_count > settings.imagery_max_band_count:
        raise api_error(
            413,
            "IMAGERY_TOO_MANY_BANDS",
            f"影像波段数 {band_count} 超过上限 {settings.imagery_max_band_count}。",
        )

    width = int(meta.get("width") or 0)
    height = int(meta.get("height") or 0)
    working_width, working_height, _ = _rescaled_shape(
        width, height, settings.imagery_working_max_dimension
    )
    itemsize = np.dtype(str(meta.get("dtype") or "uint8")).itemsize
    if min(width, height, band_count) <= 0:
        raise api_error(422, "INVALID_GEOTIFF", "影像尺寸和波段数必须为正数。")
    peak_bytes = working_width * working_height * (2 * itemsize + 3) + 64 * 1024 * 1024
    if peak_bytes > getattr(settings, "imagery_preprocess_max_bytes", 384 * 1024 * 1024):
        raise api_error(413, "IMAGERY_MEMORY_BUDGET", "影像预处理超过内存预算，请缩小范围或调整工作图尺寸。")
    working_bytes = band_count * working_width * working_height * itemsize
    if working_bytes > settings.imagery_max_working_bytes:
        raise api_error(
            413,
            "IMAGERY_WORKING_TOO_LARGE",
            f"影像工作图预算 {working_bytes} 字节超过上限 {settings.imagery_max_working_bytes}。",
        )


def _create_working_tif(source_path: Path, working_path: Path, settings) -> dict[str, Any]:
    """生成缩放/压缩后的工作图。逐波段读写（G2）：峰值内存 = 单波段工作数组，
    不再一次性读入全部波段（修复前 1000 波段 512x512 的 517KB 上传即可致 750MB 峰值；
    其中 dataset_mask 亦会物化 count×H×W 的整栈 mask，改为逐波段累积，与
    dataset_mask 在无 nodata/命中 nodata/未命中 nodata/alpha/缩放 5 类输入下逐位一致）。"""
    import numpy as np
    import rasterio
    from rasterio.enums import ColorInterp, MaskFlags, Resampling

    with rasterio.Env(GDAL_CACHEMAX=64 * 1024 * 1024), rasterio.open(source_path) as src:
        _validate_band_budget({"width": src.width, "height": src.height,
            "band_count": src.count, "dtype": src.dtypes[0]}, settings)
        working_width, working_height, resampled = _rescaled_shape(
            src.width,
            src.height,
            settings.imagery_working_max_dimension,
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
        colorinterp = src.colorinterp
        descriptions = src.descriptions
        tags = src.tags()
        band_tags = [src.tags(index) for index in src.indexes]
        scales, offsets, units = src.scales, src.offsets, src.units

        with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(working_path, "w", **profile) as dst:
            # 逐波段读写：每波段单独 read→write，重采样规则与修复前的整读语义一致
            # （resampled 时普通波段 bilinear、alpha 波段 nearest；未 resampled 时 nearest）。
            # Match rasterio.dataset_mask without allocating a count×H×W stack:
            # explicit/shared mask first; shadow RGBA uses B4; otherwise OR.
            # The analysis tool later intersects only its required bands.
            # https://rasterio.readthedocs.io/en/stable/topics/masks.html#dataset-masks
            mask_index = (1 if MaskFlags.per_dataset in src.mask_flag_enums[0]
                          else 4 if src.count == 4 and colorinterp[0] == ColorInterp.red else None)
            valid_mask = np.zeros((working_height, working_width), dtype="uint8")
            for index, interpretation in enumerate(colorinterp, 1):
                if resampled and interpretation.name != "alpha":
                    resampling = Resampling.bilinear
                else:
                    resampling = Resampling.nearest
                band = src.read(
                    index,
                    out_shape=(working_height, working_width),
                    resampling=resampling,
                )
                dst.write(band, index)
                if mask_index is None or index == mask_index:
                    band_mask = src.read_masks(
                        index, out_shape=(working_height, working_width), resampling=Resampling.nearest,
                    )
                    if mask_index is None:
                        valid_mask |= band_mask > 0
                    else:
                        valid_mask = band_mask
                del band
            dst.write_mask(valid_mask)
            dst.colorinterp = colorinterp
            dst.descriptions = descriptions
            dst.update_tags(**tags)
            dst.scales, dst.offsets = scales, offsets
            if any(units):
                dst.units = tuple(unit or "" for unit in units)
            for index, metadata in enumerate(band_tags, 1):
                dst.update_tags(index, **metadata)

    from app.services.raster_semantics import grid_context
    grids = grid_context(working_path)
    source_size = source_path.stat().st_size
    working_size = working_path.stat().st_size
    return {
        **grids,
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
    from app.services.raster_preview import generate_preview, RasterPreviewBudgetError
    try:
        generate_preview(source_path, output_path, max_dimension)
    except RasterPreviewBudgetError as exc:
        raise api_error(413, "IMAGERY_MEMORY_BUDGET", "影像预览超过内存预算，请缩小预览尺寸。") from exc


async def _write_upload_to_temp(file: UploadFile, max_bytes: int, suffix: str) -> Path:
    try:
        uploaded = await stream_upload_to_temp(
            file,
            max_bytes=max_bytes,
            suffix=suffix,
        )
    except UploadSizeExceeded as exc:
        raise api_error(413, "FILE_TOO_LARGE", "文件超过大小限制") from exc
    return uploaded.path


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
    payload = {key: value for key, value in meta.items() if key not in {"filename", "imagery_id"}}
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
        raise api_error(404, "IMAGERY_NOT_FOUND", "Imagery was not found.")


def _read_metadata_only(dest_dir: Path) -> dict[str, Any]:
    """读 metadata.json（不校验 owner）。文件缺失/损坏 → 对应 HTTP 错误。"""
    meta_file = dest_dir / "metadata.json"
    if not meta_file.exists():
        raise api_error(404, "IMAGERY_NOT_FOUND", "Imagery was not found.")
    meta = _read_metadata(meta_file)
    if meta is None:
        raise api_error(500, "INTERNAL_ERROR", "Imagery metadata is invalid.")
    return meta


async def _read_owned_metadata(dest_dir: Path) -> dict[str, Any]:
    """读 metadata.json 并校验 owner（DB 优先 + json 兜底）。imagery_id 取自目录名。"""
    meta = _read_metadata_only(dest_dir)
    await _ensure_imagery_owner_db_first(dest_dir.name, meta)
    return meta


@router.post("/upload", response_model=ImageryMetadata)
async def upload_imagery(file: UploadFile = File(...)) -> ImageryMetadata:
    settings = get_settings()
    owner_user_id = get_current_user_id()

    if not file.filename or not file.filename.lower().endswith((".tif", ".tiff")):
        raise api_error(400, "INVALID_REQUEST", "仅支持 GeoTIFF (.tif/.tiff) 格式")

    suffix = Path(file.filename).suffix.lower()
    temp_path = await _write_upload_to_temp(file, settings.imagery_max_file_bytes, suffix)
    try:
        meta = await await_settled_operation(asyncio.to_thread(_extract_metadata, temp_path))
    except asyncio.CancelledError:
        _safe_unlink(temp_path)
        raise
    except Exception as exc:
        _safe_unlink(temp_path)
        logger.warning("Failed to parse uploaded GeoTIFF: %s", file.filename, exc_info=True)
        raise api_error(422, "INVALID_GEOTIFF", "无法解析 GeoTIFF，请确认文件格式和影像完整性") from exc

    # G2 波段预算校验（413，不得落入下方 422 转换）：超限拒绝并清理临时文件。
    try:
        _validate_band_budget(meta, settings)
    except HTTPException:
        _safe_unlink(temp_path)
        raise

    imagery_id = uuid.uuid4().hex[:12]
    dest_dir: Path | None = None
    directory_created = False
    try:
        dest_dir = _imagery_dir(imagery_id)
        dest_dir.mkdir(parents=True, exist_ok=False)
        directory_created = True
        results_dir = dest_dir / "results"
        results_dir.mkdir(exist_ok=True)
    except FileExistsError as exc:
        _safe_unlink(temp_path)
        if directory_created:
            _safe_rmtree(dest_dir)
        raise api_error(409, "CONFLICT", "影像 ID 冲突，请重试上传。") from exc
    except OSError as exc:
        _safe_unlink(temp_path)
        if directory_created:
            _safe_rmtree(dest_dir)
        raise api_error(503, "STORAGE_UNAVAILABLE", "影像存储目录暂不可用，本次没有完成导入。") from exc

    source_path = dest_dir / "source.tif"
    working_path = dest_dir / "working.tif"
    preview_path = results_dir / "preview.png"
    try:
        await await_settled_operation(asyncio.to_thread(shutil.move, str(temp_path), source_path))
        async with resource_semaphore("raster", getattr(settings, "raster_preprocess_max_concurrent", 2)):
            working_meta = await await_settled_operation(asyncio.to_thread(_create_working_tif, source_path, working_path, settings))
            await await_settled_operation(asyncio.to_thread(_generate_preview, source_path, preview_path, settings.imagery_preview_max_dimension))
    except (asyncio.CancelledError, HTTPException):
        _safe_unlink(temp_path)
        _safe_rmtree(dest_dir)
        raise
    except Exception as exc:
        _safe_unlink(temp_path)
        _safe_rmtree(dest_dir)
        logger.warning("Failed to process uploaded GeoTIFF: %s", file.filename, exc_info=True)
        raise api_error(422, "INVALID_GEOTIFF", "无法处理 GeoTIFF，请确认影像波段、尺寸和压缩格式") from exc

    try:
        sha256 = await await_settled_operation(asyncio.to_thread(_file_sha256, source_path))
    except OSError as exc:
        _safe_rmtree(dest_dir)
        raise api_error(503, "STORAGE_UNAVAILABLE", "影像校验读取失败，本次没有完成导入。") from exc
    except BaseException:
        _safe_rmtree(dest_dir)
        raise
    meta = {
        **meta,
        **working_meta,
        "filename": file.filename,
        "preview_url": f"/api/imagery/{imagery_id}/results/preview.png",
        "sha256": sha256,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "owner_user_id": owner_user_id,
    }
    try:
        _write_json_atomic(dest_dir / "metadata.json", meta)
        await _persist_imagery_record(imagery_id, dest_dir, meta, owner_user_id)
    except (asyncio.CancelledError, HTTPException) as exc:
        # Pending compensation keeps private evidence. If retaining that evidence
        # itself failed, preserve the sole local copy for an operator to inspect.
        if not getattr(exc, "preserve_local_directory", False):
            _safe_rmtree(dest_dir)
        raise
    except OSError as exc:
        _safe_rmtree(dest_dir)
        raise api_error(503, "STORAGE_UNAVAILABLE", "影像元信息保存失败，本次没有完成导入。") from exc

    logger.info(
        "Imagery uploaded: %s, %s, %s bands, working=%sx%s",
        imagery_id,
        file.filename,
        meta["band_count"],
        meta["working_width"],
        meta["working_height"],
    )
    payload = {key: value for key, value in meta.items() if key not in {"filename", "imagery_id"}}
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
                payload = {k: v for k, v in meta.items() if k not in {"filename", "imagery_id"}}
                merged[row["imagery_id"]] = ImageryMetadata(
                    imagery_id=row["imagery_id"], filename=filename, **payload
                )
        except Exception as exc:
            if not is_missing_schema_error(exc):
                logger.exception("影像列表 DB 查询失败（回落本地扫描结果）")
    return list(merged.values())


@router.post("/cleanup", response_model=CleanupResult)
async def cleanup_imagery(_admin: dict = Depends(require_admin)) -> CleanupResult:
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
                raise api_error(404, "IMAGERY_NOT_FOUND", "Imagery was not found.")
            meta = dict(row.get("metadata") or {})
            if meta:
                return meta
    # 兜底：本地 metadata.json（含 owner 校验）。
    return await _read_owned_metadata(_imagery_dir(imagery_id))


@router.get("/{imagery_id}", response_model=ImageryMetadata)
async def get_imagery(imagery_id: str) -> ImageryMetadata:
    meta = await _load_owned_meta_db_first(imagery_id)
    filename = str(meta.get("filename") or "source.tif")
    payload = {k: v for k, v in meta.items() if k not in {"filename", "imagery_id"}}
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
            raise api_error(404, "IMAGERY_NOT_FOUND", "Imagery was not found.")
        return
    # DB 无此行 → 回落本地 metadata.json（必须存在且 owner 匹配）。
    await _read_owned_metadata(dest_dir)


def _result_media_type(filename: str) -> str:
    if filename.endswith(".geojson"):
        return "application/geo+json"
    if filename.endswith(".json"):
        return "application/json"
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
            raise api_error(404, "IMAGERY_NOT_FOUND", "结果文件不存在")
        # 代理流式：保留 owner 鉴权（不用 presigned URL，避免绕过校验越权）。
        return StreamingResponse(
            stream,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )

    # local 后端：原逻辑，本地 metadata.json owner 校验 + FileResponse。
    await _read_owned_metadata(result_path.parent.parent)
    if not result_path.exists():
        raise api_error(404, "IMAGERY_NOT_FOUND", "结果文件不存在")
    return FileResponse(result_path, media_type=media_type, filename=filename)

from __future__ import annotations

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
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.core.paths import imagery_root
from app.core.settings import get_settings

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


@router.post("/upload", response_model=ImageryMetadata)
async def upload_imagery(file: UploadFile = File(...)) -> ImageryMetadata:
    settings = get_settings()

    if not file.filename or not file.filename.lower().endswith((".tif", ".tiff")):
        raise HTTPException(status_code=400, detail="仅支持 GeoTIFF (.tif/.tiff) 格式")

    suffix = Path(file.filename).suffix.lower()
    temp_path = await _write_upload_to_temp(file, settings.imagery_max_file_bytes, suffix)
    try:
        meta = _extract_metadata(temp_path)
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
        shutil.move(str(temp_path), source_path)
        working_meta = _create_working_tif(source_path, working_path, settings)
        _generate_preview(source_path, preview_path, settings.imagery_preview_max_dimension)
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
        "sha256": _file_sha256(source_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json_atomic(dest_dir / "metadata.json", meta)

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
    root = _imagery_root()
    results: list[ImageryMetadata] = []
    if not root.exists():
        return results
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not IMAGERY_ID_PATTERN.fullmatch(entry.name):
            continue
        meta_file = entry / "metadata.json"
        if not meta_file.exists():
            continue
        meta = _read_metadata(meta_file)
        if meta is None:
            continue
        results.append(_metadata_response(entry, meta))
    return results


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


@router.get("/{imagery_id}", response_model=ImageryMetadata)
async def get_imagery(imagery_id: str) -> ImageryMetadata:
    dest_dir = _imagery_dir(imagery_id)
    meta_file = dest_dir / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="影像不存在")
    meta = _read_metadata(meta_file)
    if meta is None:
        raise HTTPException(status_code=500, detail="影像元数据损坏")
    return _metadata_response(dest_dir, meta)


@router.delete("/{imagery_id}", response_model=DeleteResult)
async def delete_imagery(imagery_id: str) -> DeleteResult:
    dest_dir = _imagery_dir(imagery_id)
    if not dest_dir.exists():
        raise HTTPException(status_code=404, detail="影像不存在")
    _safe_rmtree(dest_dir)
    return DeleteResult(imagery_id=imagery_id, deleted=not dest_dir.exists())


@router.get("/{imagery_id}/results/{filename}")
async def get_result_file(imagery_id: str, filename: str) -> FileResponse:
    result_path = _safe_result_path(imagery_id, filename)
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")
    media_type = "image/png" if filename.endswith(".png") else "image/tiff"
    return FileResponse(result_path, media_type=media_type, filename=filename)

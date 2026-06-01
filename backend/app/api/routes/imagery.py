from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.shared.settings import get_settings

router = APIRouter(prefix="/imagery", tags=["imagery"])
logger = logging.getLogger(__name__)


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


def _imagery_root() -> Path:
    settings = get_settings()
    root = Path(settings.imagery_upload_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[3] / root
    root.mkdir(parents=True, exist_ok=True)
    return root


def _imagery_dir(imagery_id: str) -> Path:
    return _imagery_root() / imagery_id


def _extract_metadata(tif_path: Path) -> dict[str, Any]:
    import rasterio
    with rasterio.open(tif_path) as src:
        return {
            "crs": str(src.crs) if src.crs else None,
            "bounds": list(src.bounds),
            "width": src.width,
            "height": src.height,
            "band_count": src.count,
            "pixel_size": list(src.res),
            "dtype": src.dtypes[0],
        }


@router.post("/upload", response_model=ImageryMetadata)
async def upload_imagery(file: UploadFile = File(...)) -> ImageryMetadata:
    settings = get_settings()

    if not file.filename or not file.filename.lower().endswith((".tif", ".tiff")):
        raise HTTPException(status_code=400, detail="仅支持 GeoTIFF (.tif/.tiff) 格式")

    imagery_id = uuid.uuid4().hex[:12]
    dest_dir = _imagery_dir(imagery_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "results").mkdir(exist_ok=True)

    source_path = dest_dir / "source.tif"
    total_bytes = 0
    with open(source_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > settings.imagery_max_file_bytes:
                source_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="文件超过大小限制")
            f.write(chunk)

    try:
        meta = _extract_metadata(source_path)
    except Exception as exc:
        source_path.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"无法解析GeoTIFF: {exc}")

    meta_path = dest_dir / "metadata.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")

    logger.info(f"Imagery uploaded: {imagery_id}, {file.filename}, {meta['band_count']} bands")
    return ImageryMetadata(imagery_id=imagery_id, filename=file.filename or "", **meta)


@router.get("", response_model=list[ImageryMetadata])
async def list_imagery() -> list[ImageryMetadata]:
    root = _imagery_root()
    results: list[ImageryMetadata] = []
    if not root.exists():
        return results
    for entry in sorted(root.iterdir()):
        meta_file = entry / "metadata.json"
        if not meta_file.exists():
            continue
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        results.append(ImageryMetadata(imagery_id=entry.name, filename="source.tif", **meta))
    return results


@router.get("/{imagery_id}", response_model=ImageryMetadata)
async def get_imagery(imagery_id: str) -> ImageryMetadata:
    dest_dir = _imagery_dir(imagery_id)
    meta_file = dest_dir / "metadata.json"
    if not meta_file.exists():
        raise HTTPException(status_code=404, detail="影像不存在")
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    return ImageryMetadata(imagery_id=imagery_id, filename="source.tif", **meta)


@router.get("/{imagery_id}/results/{filename}")
async def get_result_file(imagery_id: str, filename: str) -> FileResponse:
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="非法文件名")
    result_path = _imagery_dir(imagery_id) / "results" / filename
    if not result_path.exists():
        raise HTTPException(status_code=404, detail="结果文件不存在")
    media_type = "image/png" if filename.endswith(".png") else "image/tiff"
    return FileResponse(result_path, media_type=media_type, filename=filename)

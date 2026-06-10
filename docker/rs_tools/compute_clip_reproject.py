from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from PIL import Image
from rasterio.coords import BoundingBox
from rasterio.crs import CRS
from rasterio.enums import Resampling
from rasterio.warp import calculate_default_transform, reproject, transform_bounds
from rasterio.windows import from_bounds


def compute(
    *,
    input_path: str,
    output_dir: str,
    dst_crs: str | None = None,
    bbox: list[float] | None = None,
    bbox_crs: str | None = None,
    resampling: str = "nearest",
    max_dimension: int = 2048,
) -> dict[str, Any]:
    """裁剪 + 重投影（rasterio.warp，无模型权重）。

    - dst_crs：目标坐标系（EPSG 码或 WKT/PROJ 串）。为空则保持源 CRS（仅裁剪）。
    - bbox：裁剪范围 [minx, miny, maxx, maxy]。为空则不裁剪（仅重投影/复制）。
    - bbox_crs：bbox 所在坐标系。为空则视为与源 CRS 相同。
    - 输出重投影/裁剪后的多波段 .tif + 真彩色预览 PNG。
    """
    inp = Path(input_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not inp.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if dst_crs is None and bbox is None:
        raise ValueError("clip_reproject requires at least one of dst_crs or bbox")

    resampling_enum = _resampling(resampling)

    with rasterio.open(inp) as src:
        if src.crs is None:
            raise ValueError("Source raster has no CRS; cannot clip or reproject")
        src_crs = src.crs
        target_crs = _parse_crs(dst_crs) if dst_crs else src_crs

        # 1) 先在源坐标系里按 bbox 裁剪（若提供），避免对全图重采样。
        if bbox is not None:
            window_bounds = _clip_bounds_in_src_crs(src, bbox, bbox_crs, src_crs)
            window = from_bounds(*window_bounds, transform=src.transform)
            window = window.round_offsets().round_lengths()
            if window.width < 1 or window.height < 1:
                raise ValueError("bbox does not overlap the raster extent")
            data = src.read(window=window)
            src_transform = src.window_transform(window)
            src_height, src_width = data.shape[1], data.shape[2]
        else:
            data = src.read()
            src_transform = src.transform
            src_height, src_width = src.height, src.width

        profile = src.profile.copy()
        nodata = src.nodata
        band_count = src.count
        dtype = src.dtypes[0]

    # 2) 重投影到目标坐标系（若目标与源一致，warp 等价于按裁剪结果写出）。
    src_bounds = rasterio.transform.array_bounds(src_height, src_width, src_transform)
    dst_transform, dst_width, dst_height = calculate_default_transform(
        src_crs,
        target_crs,
        src_width,
        src_height,
        left=src_bounds[0],
        bottom=src_bounds[1],
        right=src_bounds[2],
        top=src_bounds[3],
    )
    if dst_width < 1 or dst_height < 1:
        raise ValueError("Reprojection produced an empty raster")

    destination = np.zeros((band_count, dst_height, dst_width), dtype=data.dtype)
    for band_index in range(band_count):
        reproject(
            source=data[band_index],
            destination=destination[band_index],
            src_transform=src_transform,
            src_crs=src_crs,
            dst_transform=dst_transform,
            dst_crs=target_crs,
            src_nodata=nodata,
            dst_nodata=nodata,
            resampling=resampling_enum,
        )

    output_tif = "clip_reproject.tif"
    output_png = "clip_reproject_colored.png"
    profile.update(
        driver="GTiff",
        height=dst_height,
        width=dst_width,
        transform=dst_transform,
        crs=target_crs,
        count=band_count,
        dtype=dtype,
    )
    if nodata is not None:
        profile.update(nodata=nodata)
    with rasterio.open(out / output_tif, "w", **profile) as dst:
        dst.write(destination)

    out_bounds = rasterio.transform.array_bounds(dst_height, dst_width, dst_transform)
    # geospatial bounds 统一用 WGS84 经纬度（前端叠加用）。
    bounds_wgs84 = list(transform_bounds(target_crs, CRS.from_epsg(4326), *out_bounds))

    stats = {
        "src_crs": str(src_crs),
        "dst_crs": str(target_crs),
        "width": int(dst_width),
        "height": int(dst_height),
        "band_count": int(band_count),
        "clipped": bbox is not None,
        "reprojected": str(target_crs) != str(src_crs),
        "bounds_wgs84": bounds_wgs84,
        "output_tif": output_tif,
        "output_png": output_png,
    }
    (out / "clip_reproject_stats.json").write_text(json.dumps(stats), encoding="utf-8")

    _write_preview_png(destination, nodata, out / output_png, max_dimension)
    return stats


def _resampling(name: str) -> Resampling:
    table = {
        "nearest": Resampling.nearest,
        "bilinear": Resampling.bilinear,
        "cubic": Resampling.cubic,
    }
    key = (name or "nearest").lower()
    if key not in table:
        raise ValueError(f"Unsupported resampling: {name}")
    return table[key]


def _parse_crs(value: str) -> CRS:
    text = str(value).strip()
    try:
        if text.upper().startswith("EPSG:"):
            return CRS.from_epsg(int(text.split(":", 1)[1]))
        if text.isdigit():
            return CRS.from_epsg(int(text))
        return CRS.from_string(text)
    except Exception as exc:
        raise ValueError(f"Invalid CRS: {value}") from exc


def _clip_bounds_in_src_crs(
    src: Any,
    bbox: list[float],
    bbox_crs: str | None,
    src_crs: CRS,
) -> tuple[float, float, float, float]:
    if len(bbox) != 4:
        raise ValueError("bbox must be [minx, miny, maxx, maxy]")
    minx, miny, maxx, maxy = (float(v) for v in bbox)
    if minx >= maxx or miny >= maxy:
        raise ValueError("bbox must satisfy minx<maxx and miny<maxy")

    if bbox_crs:
        source = _parse_crs(bbox_crs)
        if str(source) != str(src_crs):
            minx, miny, maxx, maxy = transform_bounds(source, src_crs, minx, miny, maxx, maxy)

    raster = src.bounds
    inter = BoundingBox(
        max(minx, raster.left),
        max(miny, raster.bottom),
        min(maxx, raster.right),
        min(maxy, raster.top),
    )
    if inter.left >= inter.right or inter.bottom >= inter.top:
        raise ValueError("bbox does not overlap the raster extent")
    return (inter.left, inter.bottom, inter.right, inter.top)


def _write_preview_png(
    data: np.ndarray,
    nodata: float | None,
    out_path: Path,
    max_dimension: int,
) -> None:
    band_count = data.shape[0]
    if band_count >= 3:
        # 默认按 GF-2 波序取真彩色 red=3,green=2,blue=1（1-based -> index 2,1,0）。
        channels = [data[2], data[1], data[0]]
    else:
        channels = [data[0], data[0], data[0]]

    rgb = np.dstack([_stretch_to_byte(c.astype(np.float32), nodata) for c in channels])
    image = Image.fromarray(rgb, mode="RGB").convert("RGBA")
    if max(image.size) > max_dimension:
        image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    image.save(out_path, optimize=True)


def _stretch_to_byte(values: np.ndarray, nodata: float | None) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if nodata is not None:
        finite = finite[finite != nodata]
    if finite.size == 0:
        return np.zeros(values.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [2, 98])
    if high <= low:
        return np.zeros(values.shape, dtype=np.uint8)
    scaled = (values - low) / (high - low)
    return (np.clip(scaled, 0, 1) * 255).astype(np.uint8)

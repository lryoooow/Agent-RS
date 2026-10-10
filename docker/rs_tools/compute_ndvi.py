from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import rasterio

from raster_utils import (
    UncalibratedInputError,
    as_numeric,
    calibrate_reflectance,
    pixel_counts,
    safe_ratio,
    require_valid_pixels,
    valid_mask,
)


def compute(
    *,
    input_path: str,
    output_dir: str,
    red_band: int = 3,
    nir_band: int = 4,
) -> dict[str, Any]:
    inp = Path(input_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not inp.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with rasterio.open(inp) as src:
        if red_band < 1 or nir_band < 1:
            raise ValueError(
                f"Band indexes must be 1-based positive integers: red={red_band}, nir={nir_band}"
            )
        if red_band > src.count or nir_band > src.count:
            raise ValueError(
                f"Requested bands ({red_band}, {nir_band}) exceed available bands ({src.count})"
            )
        red = src.read(red_band)
        nir = src.read(nir_band)
        profile = src.profile.copy()

        # 统一无效像元判定（A3）：NaN/nodata 元数据不再污染统计量。
        valid = valid_mask(src, (red, nir), band_indexes=(red_band, nir_band))
        require_valid_pixels(valid)

        # Only declared calibration is applied. An entirely unknown generic DN
        # input may yield a labelled relative ratio; damaged or incomplete
        # declarations and known offset-prone products must fail explicitly.
        try:
            calibrated_bands, cal_info = calibrate_reflectance(src, {"red": red, "nir": nir}, band_indexes={"red": red_band, "nir": nir_band})
            calibrated = cal_info["method"] != "unknown_all_invalid"
            red, nir = calibrated_bands["red"], calibrated_bands["nir"]
        except UncalibratedInputError:
            calibrated = False
            red, nir = as_numeric(red), as_numeric(nir)
            cal_info = {"method": "uncalibrated_relative", "method_version": "reflectance-v2", "bands": {}}

    with np.errstate(over="ignore", invalid="ignore"):
        ndvi = safe_ratio(nir - red, nir + red)
    # 无效像元（nodata/NaN）置 NaN，不进 min/mean/std。
    with np.errstate(over="ignore", invalid="ignore"):
        ndvi = ndvi.astype(np.float32, copy=False)
    ndvi[~valid | ~np.isfinite(ndvi)] = np.nan
    require_valid_pixels(np.isfinite(ndvi))

    # 每次运行的输出带 uuid 后缀，重跑不覆盖历史结果（A6）。
    run_id = uuid4().hex[:16]
    output_tif = f"ndvi_{run_id}.tif"
    output_png = f"ndvi_{run_id}_colored.png"
    profile.update(dtype="float32", count=1, nodata=np.nan)
    with rasterio.open(out / output_tif, "w", **profile) as dst:
        dst.write(ndvi, 1)

    stats = _stats(ndvi)
    stats["calibrated"] = calibrated
    stats["calibration"] = cal_info
    stats["method_version"] = "ndvi-v2"
    stats["resolved_bands"] = {"red": red_band, "nir": nir_band}
    stats["input_valid_pixels"] = int(valid.sum())
    stats["math_invalid_pixels"] = int(np.count_nonzero(valid & ~np.isfinite(ndvi)))
    stats["output_tif"] = output_tif
    stats["output_png"] = output_png
    (out / f"ndvi_{run_id}_stats.json").write_text(json.dumps(stats), encoding="utf-8")

    _write_colored_png(ndvi, out / output_png)
    return stats


def _stats(ndvi: np.ndarray) -> dict[str, Any]:
    valid = ndvi[np.isfinite(ndvi)].astype(np.float64)
    total = ndvi.size
    nodata = total - valid.size
    return {
        **pixel_counts(np.isfinite(ndvi)),
        "min": float(np.min(valid)) if valid.size else 0.0,
        "max": float(np.max(valid)) if valid.size else 0.0,
        "mean": float(np.mean(valid)) if valid.size else 0.0,
        "std": float(np.std(valid)) if valid.size else 0.0,
        "nodata_pct": round(nodata / total * 100, 2) if total else 0.0,
    }


def _write_colored_png(ndvi: np.ndarray, out_path: Path) -> None:
    from PIL import Image

    h, w = ndvi.shape
    max_dim = 2048
    if max(h, w) > max_dim:
        scale = max_dim / max(h, w)
        new_h, new_w = int(h * scale), int(w * scale)
    else:
        new_h, new_w = h, w

    norm = np.nan_to_num(np.clip((ndvi + 1) / 2, 0, 1), nan=0.0)

    color_positions = np.array([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float32)
    color_values = np.array(
        [
            [166, 0, 38, 255],
            [214, 97, 0, 255],
            [255, 255, 153, 255],
            [102, 189, 51, 255],
            [0, 105, 56, 255],
        ],
        dtype=np.float32,
    )
    rgba = np.empty((*norm.shape, 4), dtype=np.uint8)
    for channel in range(4):
        rgba[..., channel] = np.interp(
            norm,
            color_positions,
            color_values[:, channel],
        ).astype(np.uint8)

    rgba[~np.isfinite(ndvi)] = [0, 0, 0, 0]

    img = Image.fromarray(rgba, mode="RGBA")
    if (new_h, new_w) != (h, w):
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    img.save(out_path, optimize=True)

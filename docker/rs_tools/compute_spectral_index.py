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


INDEX_OUTPUT_RANGES = {
    "ndwi": (-1.0, 1.0),
    "mndwi": (-1.0, 1.0),
    "ndbi": (-1.0, 1.0),
    "evi": (-1.0, 2.5),
    "savi": (-1.0, 1.0),
    "gndvi": (-1.0, 1.0),
    "ndmi": (-1.0, 1.0),
    "nbr": (-1.0, 1.0),
    "msavi": (-1.0, 1.0),
    "bsi": (-1.0, 1.0),
}

# 公式常数假设 0-1 反射率输入的指数（Huete et al. 1999 EVI 的 L=1/C1/C2、
# Huete 1988 SAVI 的 L=0.5、Qi et al. 1994 MSAVI）：必须先定标（A5），
# 拿不到定标信息 → UncalibratedInputError，不允许静默按 DN 计算。
NEED_REFLECTANCE = {"evi", "savi", "msavi"}

# 归一化差值类指数：对线性缩放不敏感，可以不定标；但带偏置的量化（Landsat）
# 能定标就定标，定不了则在 stats 标注 calibrated: false（工作单 A5.2）。


def compute(
    *,
    input_path: str,
    output_dir: str,
    index_type: str,
    blue_band: int = 1,
    green_band: int = 2,
    red_band: int = 3,
    nir_band: int = 4,
    swir_band: int = 5,
) -> dict[str, Any]:
    index_type = index_type.lower()
    if index_type not in INDEX_OUTPUT_RANGES:
        raise ValueError(f"Unsupported spectral index: {index_type}")

    inp = Path(input_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    with rasterio.open(inp) as src:
        _validate_bands(src.count, index_type, blue_band, green_band, red_band, nir_band, swir_band)
        profile = src.profile.copy()

        band_numbers = {
            "blue": blue_band, "green": green_band, "red": red_band,
            "nir": nir_band, "swir": swir_band,
        }
        needed = {
            "ndwi": ("green", "nir"),
            "mndwi": ("green", "swir"),
            "ndbi": ("nir", "swir"),
            "evi": ("blue", "red", "nir"),
            "savi": ("red", "nir"),
            "gndvi": ("green", "nir"),
            "ndmi": ("nir", "swir"),
            "nbr": ("nir", "swir"),
            "msavi": ("red", "nir"),
            "bsi": ("blue", "red", "nir", "swir"),
        }[index_type]
        raw = {name: src.read(band_numbers[name]) for name in needed}

        # 统一无效像元判定（A3）：NaN/nodata 元数据不再污染统计量。
        valid = valid_mask(src, raw.values(), band_indexes=tuple(band_numbers[name] for name in needed))
        require_valid_pixels(valid)

        if index_type in NEED_REFLECTANCE:
            bands, cal_info = calibrate_reflectance(src, raw, band_indexes={name: band_numbers[name] for name in needed})  # 失败即抛 UncalibratedInputError
            calibrated = True
        else:
            try:
                bands, cal_info = calibrate_reflectance(src, raw, band_indexes={name: band_numbers[name] for name in needed})
                calibrated = cal_info["method"] != "unknown_all_invalid"
            except UncalibratedInputError:
                bands, calibrated = {name: as_numeric(data) for name, data in raw.items()}, False
                cal_info = {"method": "uncalibrated_relative", "method_version": "reflectance-v2", "bands": {}}

    blue = bands.get("blue")
    green = bands.get("green")
    red = bands.get("red")
    nir = bands.get("nir")
    swir = bands.get("swir")

    if index_type == "ndwi":
        values = _safe_ratio(green - nir, green + nir)
    elif index_type == "mndwi":
        values = _safe_ratio(green - swir, green + swir)
    elif index_type == "ndbi":
        values = _safe_ratio(swir - nir, swir + nir)
    elif index_type == "evi":
        # EVI（Huete et al. 1999/2002）：2.5(nir-red)/(nir+6red-7.5blue+1)
        values = _safe_ratio(2.5 * (nir - red), nir + 6 * red - 7.5 * blue + 1)
    elif index_type == "savi":
        # SAVI（Huete 1988，L=0.5）：1.5(nir-red)/(nir+red+0.5)
        values = _safe_ratio(1.5 * (nir - red), nir + red + 0.5)
    elif index_type == "gndvi":
        values = _safe_ratio(nir - green, nir + green)
    elif index_type == "ndmi":
        values = _safe_ratio(nir - swir, nir + swir)
    elif index_type == "nbr":
        values = _safe_ratio(nir - swir, nir + swir)
    elif index_type == "msavi":
        # MSAVI（Qi et al. 1994）：(2nir+1-sqrt((2nir+1)^2-8(nir-red)))/2
        with np.errstate(over="ignore", invalid="ignore"):
            radicand = (2 * nir + 1) ** 2 - 8 * (nir - red)
            values = (2 * nir + 1 - np.sqrt(np.where(radicand >= 0, radicand, np.nan))) / 2
    else:
        values = _safe_ratio((swir + red) - (nir + blue), (swir + red) + (nir + blue))

    # 无效像元（nodata/NaN）置 NaN，不进 min/mean/std。
    with np.errstate(over="ignore", invalid="ignore"):
        values = values.astype(np.float32, copy=False)
    values[~valid | ~np.isfinite(values)] = np.nan
    require_valid_pixels(np.isfinite(values))
    # 不再 clip 到取值范围：越界是输入质量信号，如实保留并在 stats 计数
    # out_of_range_pct（工作单 A5.3）。历史 bug：clip 曾把 DN 直算的错值掩盖。

    # 每次运行的输出带 uuid 后缀，重跑不覆盖历史结果（A6）。
    run_id = uuid4().hex[:16]
    output_tif = f"{index_type}_{run_id}.tif"
    output_png = f"{index_type}_{run_id}_colored.png"
    profile.update(dtype="float32", count=1, nodata=np.nan)
    with rasterio.open(out / output_tif, "w", **profile) as dst:
        dst.write(values.astype(np.float32), 1)

    stats = _stats(values)
    lo, hi = INDEX_OUTPUT_RANGES[index_type]
    finite = np.isfinite(values)
    out_of_range = int(np.count_nonzero(finite & ((values < lo) | (values > hi))))
    stats["calibrated"] = calibrated
    stats["calibration"] = cal_info
    stats["method_version"] = "spectral-v2"
    stats["resolved_bands"] = {name: band_numbers[name] for name in needed}
    stats["input_valid_pixels"] = int(valid.sum())
    stats["math_invalid_pixels"] = int(np.count_nonzero(valid & ~np.isfinite(values)))
    stats["out_of_range_pct"] = round(out_of_range / values.size * 100, 2) if values.size else 0.0
    stats["index_type"] = index_type
    stats["output_tif"] = output_tif
    stats["output_png"] = output_png
    (out / f"{index_type}_{run_id}_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    _write_colored_png(values, out / output_png, index_type)
    return stats


def _validate_bands(count: int, index_type: str, blue: int, green: int, red: int, nir: int, swir: int) -> None:
    required = {
        "ndwi": {"green": green, "nir": nir},
        "mndwi": {"green": green, "swir": swir},
        "ndbi": {"nir": nir, "swir": swir},
        "evi": {"blue": blue, "red": red, "nir": nir},
        "savi": {"red": red, "nir": nir},
        "gndvi": {"green": green, "nir": nir},
        "ndmi": {"nir": nir, "swir": swir},
        "nbr": {"nir": nir, "swir": swir},
        "msavi": {"red": red, "nir": nir},
        "bsi": {"blue": blue, "red": red, "nir": nir, "swir": swir},
    }[index_type]
    for name, band in required.items():
        if band < 1:
            raise ValueError(f"{name}_band must be >= 1")
        if band > count:
            raise ValueError(f"{index_type.upper()} requires {name}_band={band}, but imagery has {count} bands")


def _safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    return safe_ratio(numerator, denominator)


def _stats(values: np.ndarray) -> dict[str, Any]:
    valid = values[np.isfinite(values)].astype(np.float64)
    total = values.size
    nodata = total - valid.size
    return {
        **pixel_counts(np.isfinite(values)),
        "min": float(np.min(valid)) if valid.size else 0.0,
        "max": float(np.max(valid)) if valid.size else 0.0,
        "mean": float(np.mean(valid)) if valid.size else 0.0,
        "std": float(np.std(valid)) if valid.size else 0.0,
        "nodata_pct": round(nodata / total * 100, 2) if total else 0.0,
    }


def _write_colored_png(values: np.ndarray, out_path: Path, index_type: str) -> None:
    from PIL import Image

    # 色带拉伸只用于视觉呈现（越界值在数据文件中如实保留）。
    valid = np.nan_to_num(np.clip((values + 1) / 2, 0, 1), nan=0.0)
    ramps = {
        "ndwi": np.array([[120, 57, 30, 255], [240, 240, 180, 255], [49, 130, 189, 255], [8, 48, 107, 255]], dtype=np.float32),
        "mndwi": np.array([[120, 57, 30, 255], [240, 240, 180, 255], [49, 130, 189, 255], [8, 48, 107, 255]], dtype=np.float32),
        "ndbi": np.array([[44, 123, 182, 255], [255, 255, 191, 255], [253, 174, 97, 255], [166, 97, 26, 255]], dtype=np.float32),
        "evi": np.array([[166, 0, 38, 255], [255, 255, 191, 255], [102, 189, 99, 255], [0, 104, 55, 255]], dtype=np.float32),
        "savi": np.array([[166, 0, 38, 255], [255, 255, 191, 255], [102, 189, 99, 255], [0, 104, 55, 255]], dtype=np.float32),
        "gndvi": np.array([[166, 0, 38, 255], [255, 255, 191, 255], [102, 189, 99, 255], [0, 104, 55, 255]], dtype=np.float32),
        "msavi": np.array([[166, 0, 38, 255], [255, 255, 191, 255], [102, 189, 99, 255], [0, 104, 55, 255]], dtype=np.float32),
        "ndmi": np.array([[120, 57, 30, 255], [240, 240, 180, 255], [49, 130, 189, 255], [8, 48, 107, 255]], dtype=np.float32),
        "nbr": np.array([[0, 104, 55, 255], [255, 255, 191, 255], [253, 174, 97, 255], [166, 0, 38, 255]], dtype=np.float32),
        "bsi": np.array([[44, 123, 182, 255], [255, 255, 191, 255], [253, 174, 97, 255], [166, 97, 26, 255]], dtype=np.float32),
    }
    positions = np.linspace(0, 1, len(ramps[index_type]), dtype=np.float32)
    rgba = np.empty((*valid.shape, 4), dtype=np.uint8)
    for channel in range(4):
        rgba[..., channel] = np.interp(valid, positions, ramps[index_type][:, channel]).astype(np.uint8)
    rgba[~np.isfinite(values)] = [0, 0, 0, 0]
    image = Image.fromarray(rgba, mode="RGBA")
    if max(image.size) > 2048:
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    image.save(out_path, optimize=True)

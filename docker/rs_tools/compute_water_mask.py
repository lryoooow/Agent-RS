from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio


# 输出分类编码（单波段 uint8 栅格）
NON_WATER = 0
WATER = 1
NODATA = 2


def compute(
    *,
    input_path: str,
    output_dir: str,
    green_band: int = 2,
    nir_band: int = 4,
) -> dict[str, Any]:
    """纯阈值法水体掩膜（粗筛，无模型权重）。

    分类逻辑（NDWI 相对阈值，避免写死绝对 DN）：
    - nodata：原始无效像素。
    - water：NDWI=(green-nir)/(green+nir) 偏高的像素。阈值取有效像素 NDWI 的高分位数
      与 0 的较大者（保证至少在正 NDWI 一侧），跨传感器/定标更稳。
    - non_water：其余。
    """
    inp = Path(input_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not inp.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with rasterio.open(inp) as src:
        _validate_bands(src.count, green=green_band, nir=nir_band)
        green = src.read(green_band).astype(np.float32)
        nir = src.read(nir_band).astype(np.float32)
        profile = src.profile.copy()
        src_nodata = src.nodata

    # 无效像素：优先用原始 nodata，其次把两波段全 0 视为无效。
    if src_nodata is not None:
        nodata_mask = (green == src_nodata) | (nir == src_nodata)
    else:
        nodata_mask = (green == 0) & (nir == 0)

    valid = ~nodata_mask
    with np.errstate(divide="ignore", invalid="ignore"):
        ndwi = np.where((green + nir) == 0, np.nan, (green - nir) / (green + nir))

    # 相对阈值：取有效像素 NDWI 的 85 分位数，并与 0 取较大者。
    # 水体 NDWI 通常为正，分位数法可适应不同场景的水体比例与辐射定标差异。
    valid_ndwi = ndwi[valid & np.isfinite(ndwi)]
    if valid_ndwi.size:
        water_thr = max(float(np.percentile(valid_ndwi, 85)), 0.0)
    else:
        water_thr = 0.0

    water_mask = valid & (np.nan_to_num(ndwi, nan=-1.0) >= water_thr) & (np.nan_to_num(ndwi, nan=-1.0) > 0.0)

    classification = np.full(green.shape, NON_WATER, dtype=np.uint8)
    classification[water_mask] = WATER
    classification[nodata_mask] = NODATA

    output_tif = "water_mask.tif"
    output_png = "water_mask_colored.png"
    profile.update(dtype="uint8", count=1, nodata=NODATA)
    with rasterio.open(out / output_tif, "w", **profile) as dst:
        dst.write(classification, 1)

    stats = _stats(classification)
    stats["ndwi_threshold"] = round(water_thr, 4)
    stats["output_tif"] = output_tif
    stats["output_png"] = output_png
    (out / "water_mask_stats.json").write_text(json.dumps(stats), encoding="utf-8")

    _write_colored_png(classification, out / output_png)
    return stats


def _validate_bands(count: int, *, green: int, nir: int) -> None:
    bands = {"green": green, "nir": nir}
    for name, band in bands.items():
        if band < 1:
            raise ValueError(f"{name}_band must be >= 1, got {band}")
        if band > count:
            raise ValueError(f"extract_water_mask requires {name}_band={band}, but imagery has {count} bands")


def _stats(classification: np.ndarray) -> dict[str, Any]:
    total = int(classification.size)
    if total == 0:
        return {"water_pct": 0.0, "non_water_pct": 0.0, "nodata_pct": 0.0}
    water = int(np.count_nonzero(classification == WATER))
    nodata = int(np.count_nonzero(classification == NODATA))
    non_water = total - water - nodata
    return {
        "water_pct": round(water / total * 100, 2),
        "non_water_pct": round(non_water / total * 100, 2),
        "nodata_pct": round(nodata / total * 100, 2),
    }


def _write_colored_png(classification: np.ndarray, out_path: Path) -> None:
    from PIL import Image

    # non_water=透明，water=蓝，nodata=透明
    palette = {
        NON_WATER: [0, 0, 0, 0],
        WATER: [49, 130, 189, 210],
        NODATA: [0, 0, 0, 0],
    }
    rgba = np.zeros((*classification.shape, 4), dtype=np.uint8)
    for code, color in palette.items():
        rgba[classification == code] = color

    image = Image.fromarray(rgba, mode="RGBA")
    if max(image.size) > 2048:
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    image.save(out_path, optimize=True)

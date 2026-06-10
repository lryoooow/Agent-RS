from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio


# 输出分类编码（单波段 uint8 栅格）
CLEAR = 0
CLOUD = 1
SHADOW = 2
NODATA = 3


def compute(
    *,
    input_path: str,
    output_dir: str,
    red_band: int = 3,
    green_band: int = 2,
    blue_band: int = 1,
    nir_band: int = 4,
) -> dict[str, Any]:
    """纯阈值法云/阴影/无效像素掩膜（粗筛，无模型权重）。

    分类逻辑（多光谱相对阈值，避免写死绝对 DN）：
    - nodata：原始无效像素。
    - cloud：可见光高亮（红/绿/蓝同时偏高）且植被/水体特征弱（低 NDVI、低 NDWI）。
    - shadow：近红外很低（暗像素）且不是水体。
    - clear：其余。
    """
    inp = Path(input_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not inp.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with rasterio.open(inp) as src:
        _validate_bands(src.count, red=red_band, green=green_band, blue=blue_band, nir=nir_band)
        red = src.read(red_band).astype(np.float32)
        green = src.read(green_band).astype(np.float32)
        blue = src.read(blue_band).astype(np.float32)
        nir = src.read(nir_band).astype(np.float32)
        profile = src.profile.copy()
        src_nodata = src.nodata

    # 无效像素：优先用原始 nodata，其次把四波段全 0 视为无效。
    if src_nodata is not None:
        nodata_mask = np.any(
            np.stack([band == src_nodata for band in (red, green, blue, nir)]), axis=0
        )
    else:
        nodata_mask = (red == 0) & (green == 0) & (blue == 0) & (nir == 0)

    valid = ~nodata_mask
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where((nir + red) == 0, np.nan, (nir - red) / (nir + red))
        ndwi = np.where((green + nir) == 0, np.nan, (green - nir) / (green + nir))

    brightness = (red + green + blue) / 3.0

    # 相对阈值：用有效像素的分位数，跨传感器/定标更稳。
    valid_brightness = brightness[valid]
    valid_nir = nir[valid]
    if valid_brightness.size:
        bright_hi = float(np.percentile(valid_brightness, 80))
        nir_lo = float(np.percentile(valid_nir, 20))
    else:
        bright_hi = 0.0
        nir_lo = 0.0

    # 云：可见光高亮 + 弱植被 + 弱水体。
    cloud_mask = (
        valid
        & (brightness >= bright_hi)
        & (np.nan_to_num(ndvi, nan=1.0) < 0.2)
        & (np.nan_to_num(ndwi, nan=1.0) < 0.1)
    )
    # 阴影：近红外低（暗）+ 非水体 + 非云。
    shadow_mask = (
        valid
        & ~cloud_mask
        & (nir <= nir_lo)
        & (np.nan_to_num(ndwi, nan=-1.0) < 0.2)
    )

    classification = np.full(red.shape, CLEAR, dtype=np.uint8)
    classification[shadow_mask] = SHADOW
    classification[cloud_mask] = CLOUD
    classification[nodata_mask] = NODATA

    output_tif = "cloud_mask.tif"
    output_png = "cloud_mask_colored.png"
    profile.update(dtype="uint8", count=1, nodata=NODATA)
    with rasterio.open(out / output_tif, "w", **profile) as dst:
        dst.write(classification, 1)

    stats = _stats(classification)
    stats["output_tif"] = output_tif
    stats["output_png"] = output_png
    (out / "cloud_mask_stats.json").write_text(json.dumps(stats), encoding="utf-8")

    _write_colored_png(classification, out / output_png)
    return stats


def _validate_bands(count: int, *, red: int, green: int, blue: int, nir: int) -> None:
    bands = {"red": red, "green": green, "blue": blue, "nir": nir}
    for name, band in bands.items():
        if band < 1:
            raise ValueError(f"{name}_band must be >= 1, got {band}")
        if band > count:
            raise ValueError(f"cloud_shadow_mask requires {name}_band={band}, but imagery has {count} bands")


def _stats(classification: np.ndarray) -> dict[str, Any]:
    total = int(classification.size)
    if total == 0:
        return {"cloud_pct": 0.0, "shadow_pct": 0.0, "clear_pct": 0.0, "nodata_pct": 0.0}
    cloud = int(np.count_nonzero(classification == CLOUD))
    shadow = int(np.count_nonzero(classification == SHADOW))
    nodata = int(np.count_nonzero(classification == NODATA))
    clear = total - cloud - shadow - nodata
    return {
        "cloud_pct": round(cloud / total * 100, 2),
        "shadow_pct": round(shadow / total * 100, 2),
        "clear_pct": round(clear / total * 100, 2),
        "nodata_pct": round(nodata / total * 100, 2),
    }


def _write_colored_png(classification: np.ndarray, out_path: Path) -> None:
    from PIL import Image

    # clear=透明绿，cloud=白，shadow=紫，nodata=透明
    palette = {
        CLEAR: [0, 150, 0, 60],
        CLOUD: [255, 255, 255, 220],
        SHADOW: [120, 80, 160, 200],
        NODATA: [0, 0, 0, 0],
    }
    rgba = np.zeros((*classification.shape, 4), dtype=np.uint8)
    for code, color in palette.items():
        rgba[classification == code] = color

    image = Image.fromarray(rgba, mode="RGBA")
    if max(image.size) > 2048:
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    image.save(out_path, optimize=True)

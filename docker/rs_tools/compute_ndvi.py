from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio


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
        red = src.read(red_band).astype(np.float32)
        nir = src.read(nir_band).astype(np.float32)
        profile = src.profile.copy()

    denominator = nir + red
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(denominator == 0, np.nan, (nir - red) / denominator)

    output_tif = "ndvi.tif"
    output_png = "ndvi_colored.png"
    profile.update(dtype="float32", count=1, nodata=np.nan)
    with rasterio.open(out / output_tif, "w", **profile) as dst:
        dst.write(ndvi, 1)

    stats = _stats(ndvi)
    stats["output_tif"] = output_tif
    stats["output_png"] = output_png
    (out / "ndvi_stats.json").write_text(json.dumps(stats), encoding="utf-8")

    _write_colored_png(ndvi, out / output_png)
    return stats


def _stats(ndvi: np.ndarray) -> dict[str, Any]:
    valid = ndvi[np.isfinite(ndvi)]
    total = ndvi.size
    nodata = total - valid.size
    return {
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

"""NDVI calculation module.

Core function: compute(input_path, output_dir, red_band, nir_band) -> dict
Also runnable standalone via environment variables for legacy compatibility.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import rasterio


def compute(input_path: str, output_dir: str, red_band: int = 3, nir_band: int = 4) -> dict:
    """Compute NDVI from a multispectral GeoTIFF.

    Returns stats dict with min, max, mean, std, nodata_pct.
    Outputs: ndvi.tif, ndvi_colored.png, stats.json in output_dir.
    """
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

    profile.update(dtype="float32", count=1, nodata=np.nan)
    with rasterio.open(out / "ndvi.tif", "w", **profile) as dst:
        dst.write(ndvi, 1)

    valid = ndvi[~np.isnan(ndvi)]
    total_pixels = ndvi.size
    nodata_count = total_pixels - valid.size
    stats = {
        "min": float(np.min(valid)) if valid.size > 0 else None,
        "max": float(np.max(valid)) if valid.size > 0 else None,
        "mean": float(np.mean(valid)) if valid.size > 0 else None,
        "std": float(np.std(valid)) if valid.size > 0 else None,
        "nodata_pct": round(nodata_count / total_pixels * 100, 2),
    }
    (out / "stats.json").write_text(json.dumps(stats), encoding="utf-8")

    _write_colored_png(ndvi, out / "ndvi_colored.png")
    return stats


def _write_colored_png(ndvi: np.ndarray, out_path: Path):
    """Apply an NDVI color ramp and save as RGBA PNG (max 2048px on longest side)."""
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

    nodata_mask = np.isnan(ndvi)
    rgba[nodata_mask] = [0, 0, 0, 0]

    img = Image.fromarray(rgba, mode="RGBA")
    if (new_h, new_w) != (h, w):
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    img.save(out_path, optimize=True)


if __name__ == "__main__":
    input_path = os.environ.get("INPUT_PATH", "/data/input.tif")
    output_dir = os.environ.get("OUTPUT_DIR", "/data/output")
    red_band = int(os.environ.get("RED_BAND", "3"))
    nir_band = int(os.environ.get("NIR_BAND", "4"))
    try:
        result = compute(input_path, output_dir, red_band, nir_band)
        print(
            f"NDVI computed: mean={result['mean']:.4f}, "
            f"range=[{result['min']:.4f}, {result['max']:.4f}]"
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

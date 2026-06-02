"""NDVI calculation container entry point.

Reads a multispectral GeoTIFF, computes NDVI, outputs:
  /data/output/ndvi.tif          - float32 NDVI raster
  /data/output/ndvi_colored.png  - RGBA colorized preview
  /data/output/stats.json        - statistics
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import rasterio


def main():
    input_path = Path(os.environ.get("INPUT_PATH", "/data/input.tif"))
    output_dir = Path(os.environ.get("OUTPUT_DIR", "/data/output"))
    output_dir.mkdir(parents=True, exist_ok=True)

    red_band = int(os.environ.get("RED_BAND", "3"))
    nir_band = int(os.environ.get("NIR_BAND", "4"))

    if not input_path.exists():
        print("ERROR: /data/input.tif not found", file=sys.stderr)
        sys.exit(1)

    with rasterio.open(input_path) as src:
        if red_band > src.count or nir_band > src.count:
            print(
                f"ERROR: requested bands ({red_band}, {nir_band}) "
                f"exceed available bands ({src.count})",
                file=sys.stderr,
            )
            sys.exit(1)

        red = src.read(red_band).astype(np.float32)
        nir = src.read(nir_band).astype(np.float32)
        profile = src.profile.copy()
        bounds = src.bounds

    denominator = nir + red
    with np.errstate(divide="ignore", invalid="ignore"):
        ndvi = np.where(denominator == 0, np.nan, (nir - red) / denominator)

    # Write NDVI GeoTIFF
    profile.update(dtype="float32", count=1, nodata=np.nan)
    ndvi_path = output_dir / "ndvi.tif"
    with rasterio.open(ndvi_path, "w", **profile) as dst:
        dst.write(ndvi, 1)

    # Compute statistics
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
    (output_dir / "stats.json").write_text(json.dumps(stats), encoding="utf-8")

    # Generate colorized PNG preview
    _write_colored_png(ndvi, output_dir / "ndvi_colored.png")

    print(f"NDVI computed: mean={stats['mean']:.4f}, range=[{stats['min']:.4f}, {stats['max']:.4f}]")


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
    main()

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling


MODE_BANDS = {
    "true_color": [3, 2, 1],
    "false_color": [4, 3, 2],
}


def render(
    *,
    input_path: str,
    output_dir: str,
    mode: str,
    bands: list[int] | None = None,
    max_dimension: int = 2048,
) -> dict[str, Any]:
    mode = mode.lower()
    if mode == "custom":
        if not bands or len(bands) != 3:
            raise ValueError("custom mode requires exactly 3 bands")
        bands_used = [int(item) for item in bands]
    elif mode in MODE_BANDS:
        bands_used = MODE_BANDS[mode]
    else:
        raise ValueError(f"Unsupported composite mode: {mode}")

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    with rasterio.open(input_path) as src:
        for band in bands_used:
            if band < 1 or band > src.count:
                raise ValueError(f"band {band} exceeds available band count {src.count}")
        width, height = _rescaled_shape(src.width, src.height, max_dimension)
        data = src.read(
            bands_used,
            out_shape=(3, height, width),
            resampling=Resampling.bilinear,
        ).astype(np.float32)

    rgb = np.dstack([_stretch_to_byte(channel) for channel in data])
    filename = f"composite_{mode}.png"
    Image.fromarray(rgb, mode="RGB").convert("RGBA").save(out / filename, optimize=True)
    return {
        "mode": mode,
        "bands_used": bands_used,
        "output_png": filename,
        "width": width,
        "height": height,
    }


def _rescaled_shape(width: int, height: int, max_dimension: int) -> tuple[int, int]:
    longest = max(width, height)
    if longest <= max_dimension:
        return width, height
    scale = max_dimension / longest
    return max(1, int(round(width * scale))), max(1, int(round(height * scale)))


def _stretch_to_byte(values: np.ndarray) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros(values.shape, dtype=np.uint8)
    low, high = np.percentile(finite, [2, 98])
    if high <= low:
        return np.zeros(values.shape, dtype=np.uint8)
    scaled = (values - low) / (high - low)
    return (np.clip(scaled, 0, 1) * 255).astype(np.uint8)

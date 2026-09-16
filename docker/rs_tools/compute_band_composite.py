from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import rasterio
from PIL import Image
from rasterio.enums import Resampling


def render(
    *,
    input_path: str,
    output_dir: str,
    mode: str,
    bands: list[int] | None = None,
    max_dimension: int = 2048,
) -> dict[str, Any]:
    mode = mode.lower()
    if mode not in {"true_color", "false_color", "custom"}:
        raise ValueError(f"Unsupported composite mode: {mode}")
    if not bands or len(bands) != 3:
        raise ValueError("Every composite requires three resolved bands from imagery metadata")
    bands_used = [int(item) for item in bands]

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
        )
        alpha = src.dataset_mask(out_shape=(height, width), resampling=Resampling.nearest)

    rgb = np.moveaxis(data, 0, -1) if data.dtype == np.uint8 else np.dstack([_stretch_to_byte(channel) for channel in data])
    filename = f"composite_{mode}_{uuid4().hex[:16]}.png"
    Image.fromarray(np.dstack([rgb, alpha])).save(out / filename, optimize=True)
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

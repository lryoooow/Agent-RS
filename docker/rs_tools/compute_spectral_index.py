from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio


INDEX_OUTPUT_RANGES = {
    "ndwi": (-1.0, 1.0),
    "mndwi": (-1.0, 1.0),
    "ndbi": (-1.0, 1.0),
    "evi": (-1.0, 1.0),
    "savi": (-1.0, 1.0),
    "gndvi": (-1.0, 1.0),
    "ndmi": (-1.0, 1.0),
    "nbr": (-1.0, 1.0),
    "msavi": (-1.0, 1.0),
    "bsi": (-1.0, 1.0),
}


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

        blue = _read(src, blue_band) if index_type in {"evi", "bsi"} else None
        green = _read(src, green_band) if index_type in {"ndwi", "mndwi", "gndvi"} else None
        red = _read(src, red_band) if index_type in {"evi", "savi", "msavi", "bsi"} else None
        nir = _read(src, nir_band) if index_type in {"ndwi", "ndbi", "evi", "savi", "gndvi", "ndmi", "nbr", "msavi", "bsi"} else None
        swir = _read(src, swir_band) if index_type in {"mndwi", "ndbi", "ndmi", "nbr", "bsi"} else None

    if index_type == "ndwi":
        values = _safe_ratio(green - nir, green + nir)
    elif index_type == "mndwi":
        values = _safe_ratio(green - swir, green + swir)
    elif index_type == "ndbi":
        values = _safe_ratio(swir - nir, swir + nir)
    elif index_type == "evi":
        values = _safe_ratio(2.5 * (nir - red), nir + 6 * red - 7.5 * blue + 1)
    elif index_type == "savi":
        values = _safe_ratio(1.5 * (nir - red), nir + red + 0.5)
    elif index_type == "gndvi":
        values = _safe_ratio(nir - green, nir + green)
    elif index_type == "ndmi":
        values = _safe_ratio(nir - swir, nir + swir)
    elif index_type == "nbr":
        values = _safe_ratio(nir - swir, nir + swir)
    elif index_type == "msavi":
        values = (2 * nir + 1 - np.sqrt(np.maximum((2 * nir + 1) ** 2 - 8 * (nir - red), 0.0))) / 2
    else:
        values = _safe_ratio((swir + red) - (nir + blue), (swir + red) + (nir + blue))

    values = np.clip(values, -1.0, 1.0)
    output_tif = f"{index_type}.tif"
    output_png = f"{index_type}_colored.png"
    profile.update(dtype="float32", count=1, nodata=np.nan)
    with rasterio.open(out / output_tif, "w", **profile) as dst:
        dst.write(values.astype(np.float32), 1)

    stats = _stats(values)
    stats["index_type"] = index_type
    stats["output_tif"] = output_tif
    stats["output_png"] = output_png
    (out / f"{index_type}_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    _write_colored_png(values, out / output_png, index_type)
    return stats


def _read(src, band: int) -> np.ndarray:
    return src.read(band).astype(np.float32)


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
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(denominator == 0, np.nan, numerator / denominator)


def _stats(values: np.ndarray) -> dict[str, Any]:
    valid = values[np.isfinite(values)]
    total = values.size
    nodata = total - valid.size
    return {
        "min": float(np.min(valid)) if valid.size else 0.0,
        "max": float(np.max(valid)) if valid.size else 0.0,
        "mean": float(np.mean(valid)) if valid.size else 0.0,
        "std": float(np.std(valid)) if valid.size else 0.0,
        "nodata_pct": round(nodata / total * 100, 2) if total else 0.0,
    }


def _write_colored_png(values: np.ndarray, out_path: Path, index_type: str) -> None:
    from PIL import Image

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

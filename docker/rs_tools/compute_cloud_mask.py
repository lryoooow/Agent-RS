from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import rasterio

from raster_utils import calibrate_reflectance, pixel_counts, require_valid_pixels, safe_ratio, valid_mask

# Product definitions:
# https://sentiwiki.copernicus.eu/web/s2-processing
# https://www.usgs.gov/landsat-missions/landsat-collection-2-quality-assessment-bands
# https://www.usgs.gov/landsat-missions/landsat-collection-2-known-issues
# Preserve existing result codes. Extra classes must not silently become clear.
CLEAR, CLOUD, SHADOW, NODATA = 0, 1, 2, 3
UNKNOWN, SNOW, TERRAIN_SHADOW = 4, 5, 6
QUALITY_TYPES = {"sentinel2_scl", "landsat_c2_qa_pixel"}

# Historical four-band baseline, deliberately NOT claimed to implement Fmask.
CLOUD_VIS_MEAN_MIN, CLOUD_NDVI_MAX, CLOUD_NDWI_MAX = 0.3, 0.2, 0.1
SHADOW_NIR_MAX = 0.1


class QualityMaskUnavailableError(ValueError):
    pass


class QualityMaskInvalidError(ValueError):
    pass


def compute(
    *, input_path: str, output_dir: str, method: str = "quality",
    quality_path: str | None = None, quality_type: str | None = None,
    red_band: int = 3, green_band: int = 2, blue_band: int = 1, nir_band: int = 4,
) -> dict[str, Any]:
    """Decode a sensor quality product by default; never fall back to brightness.

    ESA SCL: 8/9/10=cloud, 3=cloud shadow, 2=terrain shadow, 11=snow,
    7=unknown, 0/1=invalid, 4/5/6=unflagged surface.
    USGS Landsat C2 QA_PIXEL uses sensor-specific bit definitions. The product's
    flags are evidence, not ground-truth accuracy or proof that analysis is safe.
    method='heuristic' explicitly runs the old unvalidated bright/dark screening.
    It returns candidate percentages and null cloud/shadow/clear percentages.
    """
    inp, out = Path(input_path), Path(output_dir)
    if not inp.is_file():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if method not in {"quality", "heuristic"}:
        raise ValueError("invalid_cloud_method: method must be quality or heuristic")
    if method == "heuristic" and (quality_path is not None or quality_type is not None):
        raise ValueError("invalid_cloud_method: heuristic cannot accept quality product arguments")

    with rasterio.open(inp) as src:
        profile = src.profile.copy()
        if method == "quality":
            try:
                classification, info = _quality_classification(src, inp, quality_path, quality_type)
            except (rasterio.errors.RasterioError, OSError):
                raise QualityMaskInvalidError("quality_mask_invalid: quality product cannot be read") from None
        else:
            classification, info = _heuristic_classification(
                src, red_band=red_band, green_band=green_band, blue_band=blue_band, nir_band=nir_band,
            )
    require_valid_pixels(classification != NODATA)
    out.mkdir(parents=True, exist_ok=True)
    run_id = uuid4().hex[:16]
    output_tif, output_png = f"cloud_mask_{run_id}.tif", f"cloud_mask_{run_id}_colored.png"
    profile.update(dtype="uint8", count=1, nodata=NODATA)
    if not profile.get("tiled"):
        profile.pop("blockxsize", None)
        profile.pop("blockysize", None)
    with rasterio.open(out / output_tif, "w", **profile) as dst:
        dst.write(classification, 1)
        dst.update_tags(MASK_METHOD=info["method"], MASK_VALIDATION=info["method_validation"])
    stats = {**_stats(classification, heuristic=method == "heuristic"), **info,
             "output_tif": output_tif, "output_png": output_png}
    (out / f"cloud_mask_{run_id}_stats.json").write_text(json.dumps(stats), encoding="utf-8")
    _write_colored_png(classification, out / output_png)
    return stats


def _quality_classification(src, inp: Path, quality_path: str | None, quality_type: str | None):
    qa_path = Path(quality_path) if quality_path is not None else inp.parent / "quality.tif"
    if qa_path.resolve().parent != inp.resolve().parent or qa_path.name != "quality.tif":
        raise QualityMaskInvalidError("quality_mask_invalid: quality product must be this imagery's quality.tif")
    if not qa_path.is_file():
        raise QualityMaskUnavailableError(
            "quality_mask_unavailable: this imagery has no sensor QA/SCL product; no cloud fraction is available"
        )
    valid = np.ones((src.height, src.width), dtype=bool)
    # Read one source channel at a time, and honor every participating channel's
    # mask. QA does not require RGB/NIR or infer roles from their positions.
    for index in src.indexes:
        valid &= valid_mask(src, (src.read(index),), band_indexes=(index,))
    require_valid_pixels(valid)
    with rasterio.open(qa_path) as qa:
        if (qa.width, qa.height, qa.crs, qa.transform) != (src.width, src.height, src.crs, src.transform):
            raise QualityMaskInvalidError("quality_mask_invalid: QA dimensions/CRS/transform do not match imagery")
        if qa.count != 1 or not np.issubdtype(np.dtype(qa.dtypes[0]), np.unsignedinteger):
            raise QualityMaskInvalidError("quality_mask_invalid: QA must be one unsigned-integer channel")
        tags = qa.tags()
        kind = tags.get("QA_TYPE", "")
        if kind not in QUALITY_TYPES or (quality_type is not None and quality_type != kind):
            raise QualityMaskInvalidError("quality_mask_invalid: unknown or inconsistent QA type")
        sensor = tags.get("QA_SENSOR", "").strip()
        source, item_id = tags.get("QA_SOURCE", ""), tags.get("QA_ITEM_ID", "").strip()
        expected_source = "sentinel2" if kind == "sentinel2_scl" else "landsat"
        if source != expected_source or not item_id or not sensor:
            raise QualityMaskInvalidError("quality_mask_invalid: missing or inconsistent QA provenance")
        source_sensor = src.tags().get("SENSOR", "").strip()
        normalized = lambda value: value.lower().replace("-", "").replace(" ", "")
        if source_sensor and normalized(source_sensor) != normalized(sensor):
            raise QualityMaskInvalidError("quality_mask_invalid: sensor differs from imagery")
        qa_values = qa.read(1)
        valid &= qa.read_masks(1) > 0

    classification = np.full(qa_values.shape, UNKNOWN, dtype=np.uint8)
    if kind == "sentinel2_scl":
        if not normalized(sensor).startswith("sentinel2") or bool(np.any(qa_values > 11)):
            raise QualityMaskInvalidError("quality_mask_invalid: unsupported Sentinel-2 SCL sensor or class")
        classification[np.isin(qa_values, (4, 5, 6))] = CLEAR
        classification[np.isin(qa_values, (8, 9, 10))] = CLOUD
        classification[qa_values == 3] = SHADOW
        classification[qa_values == 2] = TERRAIN_SHADOW
        classification[qa_values == 11] = SNOW
        valid &= ~np.isin(qa_values, (0, 1))
    else:
        key = normalized(sensor)
        if key not in {"landsat4", "landsat5", "landsat7", "landsat8", "landsat9"}:
            raise QualityMaskInvalidError("quality_mask_invalid: unsupported Landsat sensor bit layout")
        if bool(np.any(qa_values > 65535)):
            raise QualityMaskInvalidError("quality_mask_invalid: QA_PIXEL values exceed uint16 bit layout")
        # bit2 is cirrus for OLI/TIRS 8-9, unused for Landsat 4-7.
        cloud_bits = (1 << 1) | (1 << 3) | ((1 << 2) if key in {"landsat8", "landsat9"} else 0)
        if key in {"landsat4", "landsat5", "landsat7"}:
            # USGS Known Issues: bit6 alone is incorrect over some 4-7 water.
            # A water flag without either cloud flag is unflagged surface.
            unflagged = ((qa_values & ((1 << 6) | (1 << 7))) != 0) & ((qa_values & cloud_bits) == 0)
        else:
            unflagged = (qa_values & (1 << 6)) != 0
        classification[unflagged] = CLEAR
        # Cloud confidence 2 is medium; 2 in other confidence fields is reserved.
        # Neither is sufficient evidence to label a pixel as unflagged surface.
        uncertain = ((qa_values >> 8) & 3) == 2
        for shift in ((10, 12, 14) if key in {"landsat8", "landsat9"} else (10, 12)):
            uncertain |= ((qa_values >> shift) & 3) == 2
        classification[uncertain] = UNKNOWN
        classification[(qa_values & (1 << 5)) != 0] = SNOW
        classification[(qa_values & (1 << 4)) != 0] = SHADOW
        classification[(qa_values & cloud_bits) != 0] = CLOUD
        valid &= (qa_values & 1) == 0
    classification[~valid] = NODATA
    return classification, {
        "method": "quality_mask", "method_version": "sensor_quality_flags_v1",
        "method_validation": "product_flags", "quality_type": kind, "quality_sensor": sensor,
        "quality_source": source, "quality_item_id": item_id,
        "cloud_policy": "SCL 8/9/10; Landsat high cloud + dilated + OLI cirrus",
        "clear_semantics": "quality product unflagged surface; not proof of analysis suitability",
        "uncertainty_policy": "unclassified SCL; absent Landsat clear/water evidence; medium/reserved confidence remains unknown",
    }


def _heuristic_classification(src, *, red_band: int, green_band: int, blue_band: int, nir_band: int):
    bands = {"red": red_band, "green": green_band, "blue": blue_band, "nir": nir_band}
    _validate_bands(src.count, **bands)
    raw = {role: src.read(index) for role, index in bands.items()}
    valid = valid_mask(src, raw.values(), band_indexes=tuple(bands.values()))
    require_valid_pixels(valid)
    refl, cal_info = calibrate_reflectance(src, raw, band_indexes=bands)
    for band in refl.values():
        valid &= np.isfinite(band)
    require_valid_pixels(valid)
    red, green, blue, nir = (refl[role] for role in ("red", "green", "blue", "nir"))
    with np.errstate(over="ignore", invalid="ignore"):
        ndvi = safe_ratio(nir - red, nir + red)
        ndwi = safe_ratio(green - nir, green + nir)
    defined = valid & np.isfinite(ndvi) & np.isfinite(ndwi)
    bright = defined & ((red + green + blue) / 3 > CLOUD_VIS_MEAN_MIN) & (ndvi < CLOUD_NDVI_MAX) & (ndwi < CLOUD_NDWI_MAX)
    dark = defined & ~bright & (nir < SHADOW_NIR_MAX) & (ndwi <= 0)
    classification = np.full(red.shape, UNKNOWN, dtype=np.uint8)
    classification[defined] = CLEAR  # Means unflagged ONLY in this explicit baseline.
    classification[bright], classification[dark], classification[~valid] = CLOUD, SHADOW, NODATA
    return classification, {
        "method": "heuristic", "method_version": "unvalidated_bright_dark_v1",
        "method_validation": "unvalidated", "threshold_method": "absolute_reflectance_candidates",
        "cloud_vis_threshold": CLOUD_VIS_MEAN_MIN, "shadow_nir_threshold": SHADOW_NIR_MAX,
        "calibration": cal_info["method"], "band_calibration": cal_info.get("bands"),
        "calibration_method_version": cal_info.get("method_version"),
        "warning": "Unvalidated bright/dark candidates are not cloud, cloud-shadow, or clear-sky estimates.",
    }


def _validate_bands(count: int, **bands: int) -> None:
    for name, band in bands.items():
        if band < 1:
            raise ValueError(f"{name}_band must be >= 1, got {band}")
        if band > count:
            raise ValueError(f"cloud_shadow_mask requires {name}_band={band}, but imagery has {count} bands")
    if len(set(bands.values())) != len(bands):
        raise ValueError("cloud_shadow_mask requires distinct spectral channels")


def _stats(classification: np.ndarray, *, heuristic: bool) -> dict[str, Any]:
    valid = classification != NODATA
    counts = pixel_counts(valid)
    total, usable = int(classification.size), int(np.count_nonzero(valid))
    stats: dict[str, Any] = dict(counts)
    for name, code in (("clear", CLEAR), ("cloud", CLOUD), ("shadow", SHADOW),
                       ("nodata", NODATA), ("unknown", UNKNOWN), ("snow", SNOW), ("terrain_shadow", TERRAIN_SHADOW)):
        count = int(np.count_nonzero(classification == code))
        stats[f"{name}_pixel_count"] = count
        stats[f"{name}_pct"] = round(count / total * 100, 2) if total else 0.0
        if name != "nodata":
            stats[f"{name}_valid_pct"] = round(count / usable * 100, 2) if usable else 0.0
    if heuristic:
        for name, old in (("candidate_bright", "cloud"), ("candidate_dark", "shadow"), ("candidate_other", "clear")):
            for suffix in ("pct", "valid_pct", "pixel_count"):
                stats[f"{name}_{suffix}"] = stats[f"{old}_{suffix}"]
        for name in ("cloud", "shadow", "clear"):
            for suffix in ("pct", "valid_pct", "pixel_count"):
                stats[f"{name}_{suffix}"] = None
    return stats


def _write_colored_png(classification: np.ndarray, out_path: Path) -> None:
    from PIL import Image

    palette = {CLEAR: [0, 0, 0, 0], CLOUD: [255, 255, 255, 220], SHADOW: [120, 80, 160, 200],
               NODATA: [0, 0, 0, 0], UNKNOWN: [255, 165, 0, 140], SNOW: [100, 200, 255, 170],
               TERRAIN_SHADOW: [160, 100, 40, 180]}
    rgba = np.zeros((*classification.shape, 4), dtype=np.uint8)
    for code, color in palette.items():
        rgba[classification == code] = color
    image = Image.fromarray(rgba, mode="RGBA")
    if max(image.size) > 2048:
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    image.save(out_path, optimize=True)

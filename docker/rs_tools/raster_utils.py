"""Shared raster validity, stable ratio arithmetic and declared reflectance calibration.

Reflectance provenance follows producer metadata, not sensor-name or value-range
heuristics. Raw ratio fallbacks must be explicitly labelled uncalibrated by callers.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

import numpy as np


class UncalibratedInputError(ValueError):
    """输入无法定标为反射率（GF-2 等无定标信息的 DN 影像）。

    str(err) 以 "uncalibrated_input:" 开头——该文本会经 MCP isError 消息带回
    runner，runner 据此映射稳定错误码 uncalibrated_input。
    """


class StaleS2CompositeError(ValueError):
    """S2 has no usable reflectance provenance; reimport or supply parameters.

    Not an UncalibratedInputError: ratio tools must not silently use raw S2 DN.
    """


class AllPixelsInvalidError(ValueError):
    """整幅影像没有有效像元。str(err) 以 "all_pixels_invalid:" 开头。"""


def valid_mask(
    src: Any, bands: Iterable[np.ndarray], *, band_indexes: Iterable[int] | None = None
) -> np.ndarray:
    """Intersect required band masks, dataset visibility, nodata and finite values.

    Nonzero alpha is visible. Zero measurements without a nodata declaration are
    valid. A mask read error is an input error, never permission to ignore a mask.
    Pass the actual 1-based indexes to include each required band's GDAL mask.
    """
    band_list = list(bands)
    if not band_list or any(b.shape != band_list[0].shape for b in band_list):
        raise ValueError("Required bands must be nonempty and share the same grid")
    valid = src.dataset_mask() > 0
    if valid.shape != band_list[0].shape:
        raise ValueError("Dataset mask and required bands must share the same grid")
    indexes = tuple(band_indexes) if band_indexes is not None else None
    if indexes is not None:
        if len(indexes) != len(band_list):
            raise ValueError("One band index is required for each band array")
        masks = src.read_masks(indexes=indexes)
        valid &= np.all(masks > 0, axis=0)
    # A dataset .msk can override GDAL's alpha-derived mask. Visibility is
    # still required even when that explicit mask says every pixel is valid.
    for index, color in enumerate(getattr(src, "colorinterp", ()), start=1):
        if getattr(color, "name", "") == "alpha":
            alpha = src.read(index)
            valid &= np.isfinite(alpha) & (alpha > 0)
    for i, band in enumerate(band_list):
        valid &= np.isfinite(band)
        nodata = src.nodatavals[indexes[i] - 1] if indexes is not None else src.nodata
        if nodata is not None and np.isfinite(nodata):
            valid &= band != nodata
    return valid


def pixel_counts(valid: np.ndarray) -> dict[str, Any]:
    """Coverage counts; legacy percentages retain total-grid denominators."""
    total = int(valid.size)
    count = int(np.count_nonzero(valid))
    return {
        "total_pixels": total,
        "valid_pixels": count,
        "nodata_pixels": total - count,
        "nodata_pct": round((total - count) / total * 100, 2) if total else 0.0,
        "percentage_denominator": "total_pixels",
    }


def require_valid_pixels(valid: np.ndarray) -> None:
    """全部像元无效时报明确错误，不允许静默输出 0% 统计（工作单 A3）。"""
    if not bool(valid.any()):
        raise AllPixelsInvalidError(
            "all_pixels_invalid: 影像全部像元无效（nodata/NaN），无法计算统计量"
        )


# ---------------- Explicit reflectance calibration ----------------

class InvalidCalibrationError(ValueError):
    """Declared calibration is invalid; never fall back to an uncalibrated ratio."""


_SENSOR_TAG_KEYS = ("sensor_id", "sensor", "satellite", "satelliteid", "spacecraft_id", "platform")
_REFLECTANCE_QUANTITIES = {"reflectance", "surface_reflectance", "boa_reflectance", "toa_reflectance"}


def _tags(src: Any, band: int | None = None) -> dict[str, str]:
    values = src.tags() if band is None else src.tags(band)
    return {str(k).lower(): str(v).strip() for k, v in values.items()}


def _parameters(tags: Mapping[str, str]) -> tuple[float, float] | None:
    present = {"refl_scale", "refl_offset"} & tags.keys()
    if not present:
        return None
    try:
        scale, offset = float(tags["refl_scale"]), float(tags["refl_offset"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidCalibrationError("invalid_calibration: scale/offset must be a complete numeric pair") from exc
    if not np.isfinite(scale) or scale <= 0 or not np.isfinite(offset):
        raise InvalidCalibrationError("invalid_calibration: scale must be finite and positive; offset must be finite")
    return scale, offset


def as_numeric(data: np.ndarray) -> np.ndarray:
    """Do not lose neighboring 32-bit integer measurements before arithmetic."""
    dtype = np.float64 if data.dtype.itemsize >= 8 or (data.dtype.kind in "iu" and data.dtype.itemsize >= 4) else np.float32
    return data.astype(dtype, copy=False)


def calibrate_reflectance(
    src: Any, bands: Mapping[str, np.ndarray], *, band_indexes: Mapping[str, int] | None = None
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Convert using declared per-band/global reflectance parameters or units.

    Pixel magnitude, sensor name and acquisition date do not prove calibration.
    REFL_APPLIED marks already converted input; original parameters remain as
    provenance. GDAL scales/offsets need an explicit reflectance unit/quantity.
    A damaged declaration or a known offset-prone product is never a raw fallback.
    """
    global_tags = _tags(src)
    global_params = _parameters(global_tags)
    sensor = next((global_tags[k] for k in _SENSOR_TAG_KEYS if global_tags.get(k)), None)
    if band_indexes is None:
        raise InvalidCalibrationError("invalid_calibration: actual band indexes are required")
    indexes = dict(band_indexes)
    if set(indexes) != set(bands) or any(i < 1 or i > src.count for i in indexes.values()):
        raise InvalidCalibrationError("invalid_calibration: required band indexes are missing or out of range")
    declarations = {role: _tags(src, index) for role, index in indexes.items()}
    has_any_declaration = bool(global_params) or any(
        any(key.startswith("refl_") for key in tags)
        or bool(src.units[indexes[role] - 1] and src.units[indexes[role] - 1].lower() not in {"dn", "digital_number", "1", "dimensionless", "unitless"})
        or (src.scales[indexes[role] - 1], src.offsets[indexes[role] - 1]) != (1.0, 0.0)
        for role, tags in declarations.items()
    )
    converted: dict[str, np.ndarray] = {}
    details: dict[str, Any] = {}
    for role, data in bands.items():
        index = indexes[role]
        tags = _tags(src, index)
        band_params = _parameters(tags)
        params = band_params or global_params
        quantities = {
            str(value).lower().replace(" ", "_")
            for value in (tags.get("refl_quantity"), tags.get("refl_unit"),
                          global_tags.get("refl_quantity"), global_tags.get("refl_unit"),
                          src.units[index - 1]) if value
        }
        input_dn = bool(quantities & {"dn", "digital_number"})
        dimensionless = bool(quantities & {"1", "dimensionless", "unitless"})
        quantities -= {"dn", "digital_number", "1", "dimensionless", "unitless"}
        if quantities - _REFLECTANCE_QUANTITIES:
            raise InvalidCalibrationError("invalid_calibration: conflicting/non-reflectance quantity declarations")
        specialized = {"surface_reflectance" if q == "boa_reflectance" else q
                       for q in quantities if q != "reflectance"}
        if len(specialized) > 1:
            raise InvalidCalibrationError("invalid_calibration: surface/TOA reflectance declarations conflict")
        quantity = next(iter(specialized)) if specialized else "reflectance" if quantities else ""
        raw_applied = tags.get("refl_applied", global_tags.get("refl_applied"))
        if raw_applied is not None and raw_applied.lower() not in {"true", "false", "1", "0"}:
            raise InvalidCalibrationError("invalid_calibration: REFL_APPLIED must be true/false")
        already = raw_applied is not None and raw_applied.lower() in {"true", "1"}
        if input_dn and already:
            raise InvalidCalibrationError("invalid_calibration: input DN unit conflicts with already-applied reflectance")
        gdal = float(src.scales[index - 1]), float(src.offsets[index - 1])
        if not np.isfinite(gdal).all() or gdal[0] <= 0:
            raise InvalidCalibrationError("invalid_calibration: invalid GDAL band scale/offset")
        nonidentity = gdal != (1.0, 0.0)
        if params is not None and nonidentity and not np.allclose(params, gdal, rtol=1e-8, atol=1e-12):
            raise InvalidCalibrationError("invalid_calibration: conflicting REFL and GDAL scale/offset")
        if input_dn and params is None and quantity and not nonidentity:
            raise InvalidCalibrationError("invalid_calibration: DN-to-reflectance conversion parameters are missing")
        if params is None and quantity:
            params = gdal
        if params is None and already:
            raise InvalidCalibrationError("invalid_calibration: applied marker requires reflectance quantity or parameters")
        if params is None:
            if has_any_declaration:
                raise InvalidCalibrationError("invalid_calibration: some required bands have calibration but this band does not")
            if "sentinel-2" in (sensor or "").lower():
                marker = " [date_unknown]" if not global_tags.get("acquisitiondate") else ""
                raise StaleS2CompositeError(
                    f"stale_s2_composite{marker}: Sentinel-2 calibration provenance is missing; "
                    "acquisition date does not identify processing baseline. Reimport the scene or provide reflectance parameters."
                )
            if "landsat" in (sensor or "").lower() or nonidentity:
                raise InvalidCalibrationError("invalid_calibration: product/reflectance calibration provenance is missing")
            raise UncalibratedInputError("uncalibrated_input: explicit reflectance units or calibration parameters are required")
        scale, offset = params
        source = tags.get("refl_source") or global_tags.get("refl_source") or (
            "band_refl_tags" if band_params else "dataset_refl_tags" if global_params else "gdal_band_units"
        )
        # Identity with explicit units is already reflectance unless the producer
        # explicitly says calibration remains to be applied.
        already = already or (raw_applied is None and params == (1.0, 0.0) and bool(quantity))
        with np.errstate(over="ignore", invalid="ignore"):
            converted[role] = as_numeric(data) if already else as_numeric(data) * scale + offset
        details[role] = {"band_index": index, "scale": scale, "offset": offset,
                         "source": source, "quantity": quantity or "reflectance",
                         "applied": True, "input_applied": already, "input_quantity": "dn" if input_dn else quantity or "unknown"}
    specialized = {v["quantity"] for v in details.values()} - {"reflectance"}
    if len(specialized) > 1:
        raise InvalidCalibrationError("invalid_calibration: required bands mix surface and TOA reflectance")
    return converted, {
        "method": "already_reflectance" if all(v["input_applied"] for v in details.values()) else "declared_reflectance",
        "method_version": "reflectance-v2", "sensor": sensor, "bands": details,
    }


def safe_ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
    """Undefined/overflowed operands produce nodata, including inf denominators."""
    valid = np.isfinite(numerator) & np.isfinite(denominator) & (denominator != 0)
    result = np.full(numerator.shape, np.nan, dtype=np.result_type(numerator, denominator, np.float32))
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        np.divide(numerator, denominator, out=result, where=valid)
    return result

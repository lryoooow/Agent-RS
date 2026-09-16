from __future__ import annotations

from typing import Any

import numpy as np
import rasterio
from rasterio.warp import transform, transform_bounds


def inspect(input_path: str) -> dict[str, Any]:
    with rasterio.open(input_path) as src:
        colors = [color.name for color in src.colorinterp]
        descriptions = [str(d or "").lower() for d in src.descriptions]
        alpha_bands = [i for i, name in enumerate(colors, 1) if name == "alpha"]
        has_nir = any(any(key in desc for key in ("nir", "near infrared", "near-infrared", "近红外")) for desc in descriptions)
        has_swir = any(any(key in desc for key in ("swir", "shortwave infrared", "短波红外")) for desc in descriptions)
        per_band_stats = []
        alpha_statistics = []
        nodata = src.nodata
        for band in range(1, src.count + 1):
            data = src.read(band).astype(np.float32)
            mask = np.isfinite(data)
            if nodata is not None:
                mask &= data != nodata
            valid = data[mask]
            if band in alpha_bands:
                dtype = np.dtype(src.dtypes[band - 1])
                opaque = float(np.iinfo(dtype).max) if np.issubdtype(dtype, np.integer) else 1.0
                alpha_statistics.append({"band": band, "opaque_value": opaque,
                    "opaque_percentage": float(np.count_nonzero(data == opaque) / data.size * 100),
                    "transparent_percentage": float(np.count_nonzero(data == 0) / data.size * 100)})
            per_band_stats.append(
                {
                    "band": band,
                    "min": float(np.min(valid)) if valid.size else None,
                    "max": float(np.max(valid)) if valid.size else None,
                    "mean": float(np.mean(valid)) if valid.size else None,
                    "std": float(np.std(valid)) if valid.size else None,
                }
            )

        bounds_wgs84 = center_wgs84 = None
        if src.crs:
            try:
                bounds = transform_bounds(src.crs, "EPSG:4326", *src.bounds, densify_pts=21)
                x, y = src.transform * (src.width / 2, src.height / 2)
                lon, lat = transform(src.crs, "EPSG:4326", [x], [y])
                if np.isfinite([*bounds, lon[0], lat[0]]).all() and -180 <= lon[0] <= 180 and -90 <= lat[0] <= 90:
                    bounds_wgs84 = list(bounds)
                    center_wgs84 = [lon[0], lat[0]]
            except (ValueError, rasterio.errors.RasterioError):
                pass
        return {
            "color_interpretations": colors,
            "alpha_bands": alpha_bands,
            "alpha_statistics": alpha_statistics,
            "bounds_wgs84": bounds_wgs84,
            "center_wgs84": center_wgs84,
            "crs": str(src.crs) if src.crs else None,
            "bounds": [float(src.bounds.left), float(src.bounds.bottom), float(src.bounds.right), float(src.bounds.top)],
            "width": src.width,
            "height": src.height,
            "band_count": src.count,
            "dtype": src.dtypes[0] if src.dtypes else "",
            "pixel_size": [float(src.res[0]), float(src.res[1])],
            "nodata": nodata,
            "per_band_stats": per_band_stats,
            "capabilities": {
                "has_blue": src.count >= 1,
                "has_green": src.count >= 2,
                "has_red": src.count >= 3,
                "has_nir": has_nir,
                "has_swir": has_swir,
            },
        }

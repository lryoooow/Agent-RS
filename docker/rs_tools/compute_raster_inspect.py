from __future__ import annotations

from typing import Any

import numpy as np
import rasterio


def inspect(input_path: str) -> dict[str, Any]:
    with rasterio.open(input_path) as src:
        per_band_stats = []
        nodata = src.nodata
        for band in range(1, src.count + 1):
            data = src.read(band).astype(np.float32)
            mask = np.isfinite(data)
            if nodata is not None:
                mask &= data != nodata
            valid = data[mask]
            per_band_stats.append(
                {
                    "band": band,
                    "min": float(np.min(valid)) if valid.size else None,
                    "max": float(np.max(valid)) if valid.size else None,
                    "mean": float(np.mean(valid)) if valid.size else None,
                    "std": float(np.std(valid)) if valid.size else None,
                }
            )

        return {
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
                "has_nir": src.count >= 4,
                "has_swir": src.count >= 5,
            },
        }

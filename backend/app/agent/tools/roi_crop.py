from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from uuid import uuid4


class ROISelectionError(ValueError):
    pass


@dataclass(frozen=True)
class ROICrop:
    path: Path
    bounds_wgs84: tuple[float, float, float, float] | None


def crop_to_roi(
    source_path: Path,
    imagery_dir: Path,
    *,
    bbox: tuple[float, float, float, float] | None,
    bbox_crs: str | None,
    pixel_bbox: tuple[float, float, float, float] | None,
) -> ROICrop:
    import rasterio
    from rasterio.crs import CRS
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, bounds as window_bounds, from_bounds

    output_path = imagery_dir / f".sam3_roi_{uuid4().hex}.tif"
    try:
        with rasterio.open(source_path) as src:
            if pixel_bbox is not None:
                x0, y0, x1, y1 = pixel_bbox
                col0 = max(0, math.floor(x0 * src.width))
                row0 = max(0, math.floor(y0 * src.height))
                col1 = min(src.width, math.ceil(x1 * src.width))
                row1 = min(src.height, math.ceil(y1 * src.height))
            elif bbox is not None:
                if src.crs is None:
                    raise ROISelectionError("影像没有坐标系，请在影像查看器中使用像素框选。")
                try:
                    requested = transform_bounds(
                        CRS.from_user_input(bbox_crs),
                        src.crs,
                        *bbox,
                        densify_pts=21,
                    )
                except Exception as exc:
                    raise ROISelectionError("无法转换选区坐标系。") from exc
                left = max(requested[0], src.bounds.left)
                bottom = max(requested[1], src.bounds.bottom)
                right = min(requested[2], src.bounds.right)
                top = min(requested[3], src.bounds.top)
                if not (left < right and bottom < top):
                    raise ROISelectionError("框选范围与当前影像不相交。")
                floating = from_bounds(left, bottom, right, top, src.transform)
                col0 = max(0, math.floor(floating.col_off))
                row0 = max(0, math.floor(floating.row_off))
                col1 = min(src.width, math.ceil(floating.col_off + floating.width))
                row1 = min(src.height, math.ceil(floating.row_off + floating.height))
            else:
                raise ROISelectionError("缺少选区参数。")

            if col1 <= col0 or row1 <= row0:
                raise ROISelectionError("选区小于一个有效像素。")
            window = Window(col0, row0, col1 - col0, row1 - row0)
            profile = src.profile.copy()
            profile.update(
                width=int(window.width),
                height=int(window.height),
                transform=src.window_transform(window),
                tiled=False,
            )
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            data = src.read(window=window)
            native_bounds = window_bounds(window, src.transform)
            bounds_wgs84 = (
                tuple(transform_bounds(src.crs, "EPSG:4326", *native_bounds, densify_pts=21))
                if src.crs is not None
                else None
            )
            valid = src.dataset_mask(window=window)
            if bbox is not None:
                import numpy as np
                from rasterio.features import geometry_mask
                from rasterio.warp import transform

                x0, y0, x1, y1 = bbox
                xs = list(np.linspace(x0, x1, 22)) + [x1] * 22 + list(np.linspace(x1, x0, 22)) + [x0] * 22
                ys = [y0] * 22 + list(np.linspace(y0, y1, 22)) + [y1] * 22 + list(np.linspace(y1, y0, 22))
                xx, yy = transform(bbox_crs, src.crs, xs, ys)
                inside = geometry_mask(
                    [{"type": "Polygon", "coordinates": [list(zip(xx, yy)) + [(xx[0], yy[0])]]}],
                    out_shape=(int(window.height), int(window.width)),
                    transform=profile["transform"],
                    invert=True,
                )
                valid = np.where(inside, valid, 0).astype("uint8")
            with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
                with rasterio.open(output_path, "w", **profile) as dst:
                    dst.write(data)
                    dst.colorinterp = src.colorinterp
                    dst.descriptions = src.descriptions
                    dst.write_mask(valid)
        return ROICrop(path=output_path, bounds_wgs84=bounds_wgs84)  # type: ignore[arg-type]
    except ROISelectionError:
        output_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise ROISelectionError("无法从影像裁出该选区。") from exc

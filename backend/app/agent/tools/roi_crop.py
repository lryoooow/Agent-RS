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
            from app.core.settings import get_settings
            settings=get_settings()
            if src.count > settings.imagery_max_band_count:
                raise ROISelectionError("影像波段数超过裁剪资源上限。")
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
            import numpy as np
            estimated=int(window.width)*int(window.height)*sum(np.dtype(dtype).itemsize for dtype in src.dtypes)
            if estimated > settings.imagery_max_working_bytes:
                raise ROISelectionError("原始选区超过裁剪产物预算，请缩小范围。")
            profile.update(
                width=int(window.width),
                height=int(window.height),
                transform=src.window_transform(window),
                tiled=False,
            )
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            native_bounds = window_bounds(window, src.transform)
            bounds_wgs84 = (
                tuple(transform_bounds(src.crs, "EPSG:4326", *native_bounds, densify_pts=21))
                if src.crs is not None
                else None
            )
            polygon = None
            if bbox is not None:
                import numpy as np
                from rasterio.features import geometry_mask
                from rasterio.warp import transform
                x0, y0, x1, y1 = bbox
                xs = list(np.linspace(x0,x1,22))+[x1]*22+list(np.linspace(x1,x0,22))+[x0]*22
                ys = [y0]*22+list(np.linspace(y0,y1,22))+[y1]*22+list(np.linspace(y1,y0,22))
                xx, yy = transform(bbox_crs, src.crs, xs, ys)
                polygon = {"type":"Polygon", "coordinates":[list(zip(xx,yy))+[(xx[0],yy[0])]]}
            with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True, GDAL_CACHEMAX=64*1024*1024):
                with rasterio.open(output_path,"w",**profile) as dst:
                    # Preserve native scale while avoiding count×entire-ROI arrays.
                    for row in range(0,int(window.height),512):
                        for col in range(0,int(window.width),512):
                            block=Window(col,row,min(512,window.width-col),min(512,window.height-row))
                            source_block=Window(window.col_off+col,window.row_off+row,block.width,block.height)
                            for band in src.indexes:
                                dst.write(src.read(band,window=source_block),band,window=block)
                            valid=src.dataset_mask(window=source_block)
                            if polygon is not None:
                                inside=geometry_mask([polygon],out_shape=valid.shape,
                                    transform=src.window_transform(source_block),invert=True)
                                valid=np.where(inside,valid,0).astype("uint8")
                            dst.write_mask(valid,window=block)
                    dst.colorinterp=src.colorinterp
                    dst.descriptions=src.descriptions
                    dst.scales, dst.offsets=src.scales, src.offsets
                    dst.update_tags(**src.tags())
                    for band in src.indexes: dst.update_tags(band,**src.tags(band))
        return ROICrop(path=output_path, bounds_wgs84=bounds_wgs84)  # type: ignore[arg-type]
    except ROISelectionError:
        output_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise ROISelectionError("无法从影像裁出该选区。") from exc

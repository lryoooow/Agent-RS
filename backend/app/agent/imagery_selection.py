"""Deterministic current-image selection and cheap analysis preflight."""
from __future__ import annotations
import math
import re

def use_current_selection(query: str) -> bool:
    # An explicit resource, historical reference or multi-image task wins over the UI default.
    if re.search(r"\b[a-f0-9]{12}\b|\.tiff?\b|上一张|另一张|第一张|第二张|前一张|两张|分别|变化检测|对比|比较|检索|搜索|导入|下载|\b(compare|previous|search|import|download)\b", query, re.I):
        return False
    return bool(re.search(r"这张|当前|该影像|此影像|上传的|提取|分割|检测|分类|质检|体检|真彩色|假彩色|[Nn][Dd][VvWwBbMm][Ii]|\b(this image|current|segment|detect)\b", query, re.I))

def geo_roi_mismatch(bounds, bbox) -> bool:
    if not bounds or not bbox or len(bounds) != 4 or len(bbox) != 4: return False
    try:
        w,s,e,n = map(float, bounds)
        a,b,c,d = map(float, bbox)
        if not all(math.isfinite(v) for v in (w,s,e,n,a,b,c,d)): return False
        return not (a < e and c > w and b < n and d > s)
    except (TypeError, ValueError): return False

def grid_resolution_m(meta: dict) -> float | None:
    import rasterio
    grid = meta.get("analysis_grid") or meta
    size = grid.get("pixel_size")
    if not size or not grid.get("crs"): return None
    try:
        crs = rasterio.crs.CRS.from_user_input(grid["crs"])
        if crs.is_projected:
            value = max(abs(float(v)) for v in size) * crs.linear_units_factor[1]
        elif crs.is_geographic:
            bounds = meta.get("bounds")
            if not bounds: return None
            latitude = (bounds[1] + bounds[3]) / 2
            value = max(abs(size[0]) * math.cos(math.radians(latitude)), abs(size[1])) * 111195
        else: return None
        return value if math.isfinite(value) and value > 0 else None
    except (TypeError, ValueError, IndexError): return None

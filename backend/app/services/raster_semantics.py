"""Shared band provenance and source/analysis grid descriptions."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.imagery_persist import _extract_metadata


def raster_grid(path: Path) -> dict[str, Any]:
    import rasterio

    with rasterio.open(path) as src:
        return {"width": src.width, "height": src.height, "pixel_size": list(src.res),
                "crs": str(src.crs) if src.crs else None, "transform": list(src.transform)[:6]}


def grid_context(analysis_path: Path) -> dict[str, Any]:
    source_path = analysis_path.parent / "source.tif"
    analysis = raster_grid(analysis_path)
    source = raster_grid(source_path) if source_path.is_file() else analysis.copy()
    resampled = any(source[key] != analysis[key] for key in ("width", "height", "transform"))
    return {"source_grid": source, "analysis_grid": analysis, "resampled": resampled}


def band_semantics(path: Path) -> dict[str, Any]:
    # The source preserves original descriptions even for historical working files
    # whose writer inserted default RGB labels.
    original = path.parent / "source.tif"
    return _extract_metadata(original if original.is_file() else path)


def resolve_rgb(path: Path, requested: dict[str, int], *, explicit: bool = False) -> dict[str, int]:
    meta = band_semantics(path)
    invalid = {role: index for role, index in requested.items() if index < 1 or index > meta["band_count"]}
    if explicit and invalid:
        raise ValueError(f"影像只有 {meta['band_count']} 个波段，无法使用 {invalid}")
    roles = meta.get("band_roles") or {}
    if all(role in roles for role in ("red", "green", "blue")):
        return {role: int(roles[role]) for role in ("red", "green", "blue")}
    if explicit:
        return requested
    raise ValueError("源影像缺少可用的 RGB 波段定义；需要提供红、绿、蓝波段号，不能套用 GF-2 默认值。")


def format_grids(context: dict[str, Any]) -> list[str]:
    lines = []
    for key, label in (("source_grid", "原图网格"), ("analysis_grid", "分析网格")):
        grid = context.get(key)
        if grid:
            lines.append(f"- {label}: {grid['width']}×{grid['height']} px；像元大小 {grid.get('pixel_size')}（单位依坐标系）")
    if context.get("resampled"):
        lines.append("- 平台为推理性能主动降采样；原图保留，覆盖范围不变。质检、分类及检测使用分析网格，面积使用结果网格的实际像元面积。这不是元数据冲突，无需用户确认。")
    return lines

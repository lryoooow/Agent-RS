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


def resolve_rgb(path: Path, requested: dict[str, int], *, explicit: set[str] | bool = False) -> dict[str, int]:
    fields = {role + "_band" for role in requested} if explicit is True else (explicit or set())
    return resolve_spectral_bands(path, requested, explicit=set(fields))


class BandResolutionError(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def validate_spectral_selection(meta: dict[str, Any], selected: dict[str, int]) -> None:
    """Validate actual bands after resolving defaults, never before metadata resolution."""
    roles = meta.get("band_roles") or {}
    conflicts = meta.get("band_role_conflicts") or {}
    spectral_roles = {"red", "green", "blue", "nir", "swir", "swir1", "swir2"}
    actual_spectral = {role: index for role, index in selected.items() if role in spectral_roles}
    if len(set(actual_spectral.values())) != len(actual_spectral):
        raise BandResolutionError("invalid_bands", "不同光谱角色不能使用同一波段。")
    for role, index in selected.items():
        if index < 1:
            raise BandResolutionError("invalid_bands", "波段索引必须从 1 开始。")
        if index > meta["band_count"]:
            raise BandResolutionError("invalid_bands", f"影像只有 {meta['band_count']} 个波段，无法使用 {role}=B{index}。")
        if index in (meta.get("alpha_bands") or []):
            raise BandResolutionError("invalid_bands", f"B{index} 是 Alpha 透明度波段，不能作为 {role} 光谱波段。")
        if role not in spectral_roles:
            continue  # Display-channel names describe placement, not physical wavelengths.
        if role in conflicts:
            raise BandResolutionError("band_roles_unknown", f"ambiguous: {role} 对应多个波段 {conflicts[role]}，需要修正影像波段定义。")
        authoritative = meta.get("band_roles_source") in {"descriptions", "colorinterp", "positional_gf2", "stac_assets"}
        if authoritative and role in roles and int(roles[role]) != index:
            raise BandResolutionError("invalid_bands", f"{role}=B{index} 与影像真实角色 {role}=B{roles[role]} 冲突，不能由模型改写。")
        for declared, number in roles.items():
            if authoritative and int(number) == index and declared != role:
                if declared == "swir" and role in {"swir1", "swir2"}:
                    continue  # Qualified explicit fields can disambiguate legacy generic SWIR.
                raise BandResolutionError("invalid_bands", f"B{index} 已定义为 {declared}，不能作为 {role}。")


def resolve_spectral_bands(
    path: Path,
    requested: dict[str, int],
    *,
    explicit: set[str],
    required: set[str] | None = None,
) -> dict[str, int]:
    """Resolve missing arguments from the actual image; explicit values cannot contradict known roles."""
    meta = band_semantics(path)
    roles = meta.get("band_roles") or {}
    conflicts = meta.get("band_role_conflicts") or {}
    required = set(requested) if required is None else required
    resolved: dict[str, int] = {}
    missing: list[str] = []
    for role, value in requested.items():
        if role in required and role in conflicts:
            raise BandResolutionError("band_roles_unknown", f"ambiguous: {role} 对应多个波段 {conflicts[role]}，不能选择第一个。")
        if f"{role}_band" in explicit:
            resolved[role] = int(value)
        elif role in roles:
            resolved[role] = int(roles[role])
        elif role in required:
            missing.append(role)
        else:
            resolved[role] = int(value)
    if missing:
        raise BandResolutionError("band_roles_unknown", "影像缺少 " + "/".join(sorted(missing)) + " 的明确波段角色；不能套用默认波序或把 SWIR1/SWIR2 混同。")
    validate_spectral_selection(meta, {role: resolved[role] for role in required})
    return resolved


def format_grids(context: dict[str, Any]) -> list[str]:
    lines = []
    for key, label in (("source_grid", "原图网格"), ("analysis_grid", "分析网格")):
        grid = context.get(key)
        if grid:
            lines.append(f"- {label}: {grid['width']}×{grid['height']} px；像元大小 {grid.get('pixel_size')}（单位依坐标系）")
    if context.get("resampled"):
        lines.append("- 平台为推理性能主动降采样；原图保留，覆盖范围不变。质检、分类及检测使用分析网格，面积使用结果网格的实际像元面积。这不是元数据冲突，无需用户确认。")
    return lines

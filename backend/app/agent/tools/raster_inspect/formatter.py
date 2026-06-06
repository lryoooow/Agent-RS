from __future__ import annotations

from typing import Any


def format_raster_inspect_context(imagery_id: str, result: dict[str, Any]) -> str:
    capabilities = result.get("capabilities") or {}
    lines = [
        f"影像质检结果（ID: {imagery_id}）",
        f"- 尺寸: {result.get('width')} x {result.get('height')} px",
        f"- 波段数: {result.get('band_count')}",
        f"- 坐标系: {result.get('crs') or '未识别'}",
        f"- 像元大小: {result.get('pixel_size')}",
        f"- 数据类型: {result.get('dtype')}",
        f"- NoData: {result.get('nodata')}",
        (
            "- 指数能力: "
            f"Blue={bool(capabilities.get('has_blue'))}, "
            f"Green={bool(capabilities.get('has_green'))}, "
            f"Red={bool(capabilities.get('has_red'))}, "
            f"NIR={bool(capabilities.get('has_nir'))}, "
            f"SWIR={bool(capabilities.get('has_swir'))}"
        ),
    ]
    for item in result.get("per_band_stats", [])[:8]:
        lines.append(
            "- Band {band}: min={min}, max={max}, mean={mean}, std={std}".format(**item)
        )
    return "\n".join(lines)

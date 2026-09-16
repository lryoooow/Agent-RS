from __future__ import annotations

from typing import Any
from app.services.raster_semantics import format_grids


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
            "- 已确认的波段能力（未确认不代表可按序号猜测）: "
            f"Blue={bool(capabilities.get('has_blue'))}, "
            f"Green={bool(capabilities.get('has_green'))}, "
            f"Red={bool(capabilities.get('has_red'))}, "
            f"NIR={bool(capabilities.get('has_nir'))}, "
            f"SWIR={bool(capabilities.get('has_swir'))}"
        ),
    ]
    lines.extend(format_grids(result))
    lines.append(f"- 统一波段映射: {result.get('band_roles')}；来源: {result.get('band_roles_source')}")
    for alpha in result.get("alpha_statistics", []):
        lines.append(f"- B{alpha['band']} Alpha: 0=全透明，{alpha['opaque_value']}=全不透明；全不透明像素 {alpha['opaque_percentage']:.2f}%，全透明 {alpha['transparent_percentage']:.2f}%。均值接近上限代表基本不透明。")
    lines.append(f"- 波段颜色解释: {result.get('color_interpretations')}")
    if result.get("alpha_bands"):
        lines.append(f"- 透明度波段: {result['alpha_bands']}，不作为近红外参与指数计算。")
    lines.append(f"- 原坐标系四至（西、南、东、北）: {result.get('bounds')}")
    if result.get("bounds_wgs84"):
        lines.append(f"- WGS84 经纬度四至（西、南、东、北，度）: {result['bounds_wgs84']}")
        lines.append(f"- 影像中心（经度、纬度，度）: {result.get('center_wgs84')}")
        lines.append("以上位置由影像地理变换计算，不是地图视角中心；定位无需另行重投影影像。")
    else:
        lines.append("无法从影像计算有效经纬度；不能仅凭投影带或地图视角推断落点。")
    for item in result.get("per_band_stats", [])[:8]:
        lines.append(
            "- Band {band}: min={min}, max={max}, mean={mean}, std={std}".format(**item)
        )
    lines.append(
        "解读边界: 以上为影像元数据与逐波段统计的客观读数；波段角色（红/近红外等）"
        "已在上方标明来源，未识别的角色需结合传感器确认。位置约定不等于传感器实测定义；"
        "跨影像对比注意量纲与坐标系一致。"
    )
    return "\n".join(lines)

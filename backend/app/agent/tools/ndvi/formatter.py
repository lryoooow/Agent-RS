from app.agent.tools.common import format_spectral_provenance

def format_ndvi_context(imagery_id: str, stats: dict, result_filename: str) -> str:
    """Format NDVI results as LLM-readable context."""
    lines = [
        "## NDVI计算结果",
        "职责：只解释本次 NDVI 计算结果，不编造未计算的地物分类或面积统计。",
        "边界：结果图层与原图预览是两个独立图层；如缺少面积、地类或外业信息，需明确说明。",
        "",
        f"- 影像ID: {imagery_id}",
    ]
    if stats.get("min") is not None:
        lines.append(f"- NDVI范围: [{stats['min']:.4f}, {stats['max']:.4f}]")
        lines.append(f"- NDVI均值: {stats['mean']:.4f}")
        lines.append(f"- 标准差: {stats['std']:.4f}")
    lines.append(f"- 无效像素比例: {stats.get('nodata_pct', 0):.1f}%")
    lines.append(f"- 结果文件: {result_filename}")
    lines.append("")
    if stats.get("calibrated") is True:
        lines.append("植被参考需结合传感器、季节和局地样本验证，NDVI不直接等同植被覆盖面积。")
    else:
        lines.append("本结果未证明反射率定标，不能据此给出绝对植被覆盖或跨期定量结论。")
    lines.extend(format_spectral_provenance(stats))
    return "\n".join(lines)

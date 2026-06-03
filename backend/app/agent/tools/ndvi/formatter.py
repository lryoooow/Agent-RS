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
    lines.append("植被覆盖参考:")
    lines.append("- NDVI > 0.6: 高密度植被")
    lines.append("- 0.2 < NDVI < 0.6: 中等植被覆盖")
    lines.append("- NDVI < 0.2: 裸土/水体/人工地物")
    lines.append("")
    lines.append("回答样例:")
    lines.append("- 均值较高时：本次 NDVI 均值偏高，整体植被覆盖较好。")
    lines.append("- 无效像素较高时：无效像素比例较高，结果解读需要谨慎。")
    return "\n".join(lines)

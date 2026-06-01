def format_ndvi_context(imagery_id: str, stats: dict, result_filename: str) -> str:
    """Format NDVI results as LLM-readable context."""
    lines = [
        "## NDVI计算结果",
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
    return "\n".join(lines)

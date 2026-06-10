def format_cloud_mask_context(imagery_id: str, stats: dict, result_filename: str) -> str:
    """Format cloud/shadow mask results as LLM-readable context."""
    lines = [
        "## 云/阴影掩膜结果",
        "职责：只解释本次云/阴影掩膜的真实占比统计，不编造未返回的地物或精确云量。",
        "边界：本工具为阈值法粗筛（非精确云检模型），结果用于后续分析的质量控制参考，"
        "可能漏检薄云或误判高亮地物/暗色地表；如需精确云量需专业云检产品。",
        "",
        f"- 影像ID: {imagery_id}",
        f"- 云占比: {stats.get('cloud_pct', 0):.1f}%",
        f"- 阴影占比: {stats.get('shadow_pct', 0):.1f}%",
        f"- 晴空占比: {stats.get('clear_pct', 0):.1f}%",
        f"- 无效像素占比: {stats.get('nodata_pct', 0):.1f}%",
        f"- 结果文件: {result_filename}",
        "",
        "掩膜分类编码: 0=晴空, 1=云, 2=阴影, 3=无效。",
        "",
        "回答样例:",
        "- 云占比低时：本次影像云/阴影占比较低，整体质量较好，适合后续分析。",
        "- 云占比高时：本次影像云/阴影占比较高，建议在后续指数或分类前剔除受影响区域。",
    ]
    return "\n".join(lines)

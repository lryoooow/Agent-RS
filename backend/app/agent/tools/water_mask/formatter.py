def format_water_mask_context(imagery_id: str, stats: dict, result_filename: str) -> str:
    """Format water mask results as LLM-readable context."""
    lines = [
        "## 水体掩膜结果",
        "职责：只解释本次水体掩膜的真实占比统计，不编造未返回的地物或精确水域面积。",
        "边界：本工具为 NDWI 阈值法粗筛（非精确水体提取模型），结果用于水域范围的快速参考，"
        "可能漏检细小水体/混合像元，或在阴影、暗色地表、湿地处误判；如需精确水域面积需专业产品或人工核对。",
        "",
        f"- 影像ID: {imagery_id}",
        f"- 水体占比: {stats.get('water_pct', 0):.1f}%",
        f"- 非水体占比: {stats.get('non_water_pct', 0):.1f}%",
        f"- 无效像素占比: {stats.get('nodata_pct', 0):.1f}%",
        f"- NDWI 阈值: {stats.get('ndwi_threshold', 0)}",
        f"- 结果文件: {result_filename}",
        "",
        "掩膜分类编码: 0=非水体, 1=水体, 2=无效。",
        "",
        "回答样例:",
        "- 水体占比低时：本次影像水体占比较低，区域以陆地为主。",
        "- 水体占比高时：本次影像水体占比较高，水域分布较广，可结合时序影像做水域变化分析。",
    ]
    return "\n".join(lines)

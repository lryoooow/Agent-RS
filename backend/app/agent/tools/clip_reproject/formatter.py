def format_clip_reproject_context(imagery_id: str, stats: dict, result_filename: str) -> str:
    """Format clip/reproject results as LLM-readable context."""
    clipped = stats.get("clipped")
    reprojected = stats.get("reprojected")
    if clipped and reprojected:
        op = "裁剪 + 重投影"
    elif reprojected:
        op = "重投影"
    elif clipped:
        op = "裁剪"
    else:
        op = "复制（无实际变换）"

    lines = [
        "## 裁剪/重投影结果",
        "职责：只陈述本次裁剪/重投影的真实参数与输出范围，不编造未发生的变换。",
        "边界：本工具产出可下载的派生栅格与预览图，不会注册为新的影像 ID；"
        "如需对结果继续做指数/分类等分析，请重新上传该派生栅格。",
        "",
        f"- 影像ID: {imagery_id}",
        f"- 操作: {op}",
        f"- 源坐标系: {stats.get('src_crs')}",
        f"- 目标坐标系: {stats.get('dst_crs')}",
        f"- 输出尺寸: {stats.get('width')} x {stats.get('height')} 像素，{stats.get('band_count')} 个波段",
        f"- 结果文件: {result_filename}",
        "",
        "回答样例:",
        "- 已按目标坐标系完成重投影，输出栅格可下载；如需进一步分析请将其作为新影像上传。",
    ]
    return "\n".join(lines)

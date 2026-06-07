from __future__ import annotations

from typing import Any


def format_detect_context(imagery_id: str, result: dict[str, Any], result_filename: str) -> str:
    classes = result.get("classes") or []
    lines = [
        f"遥感目标检测完成（影像 ID: {imagery_id}，模型 PP-YOLOE-R / DOTA 15 类）。",
        f"- 结果图层: {result_filename}",
        f"- 检测目标总数: {result.get('detection_count', 0)}",
        f"- 置信度阈值: {result.get('score_threshold')}",
    ]
    if classes:
        lines.append("- 各类别数量:")
        for item in classes:
            lines.append(f"  · {item.get('label', item.get('name'))}: {item.get('count')}")
    else:
        lines.append("- 未检测到目标。")
    lines.append("解读边界: 模型基于 DOTA 航拍数据集训练，对中高分辨率光学航拍/卫星 RGB 影像效果最佳；分辨率或场景差异较大时结果仅供参考。")
    return "\n".join(lines)

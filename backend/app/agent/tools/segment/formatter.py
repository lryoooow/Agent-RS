from __future__ import annotations

from typing import Any


def format_segment_context(imagery_id: str, result: dict[str, Any], result_filename: str) -> str:
    classes = result.get("classes") or []
    lines = [
        f"遥感地物语义分割完成（影像 ID: {imagery_id}，模型 U-Net / LandCover.ai）。",
        f"- 结果图层: {result_filename}",
        f"- 影像总像素: {result.get('total_pixels', 0)}",
    ]
    if classes:
        lines.append("- 各地物类别占比:")
        for item in classes:
            label = item.get("label", item.get("name"))
            pct = item.get("percentage")
            pct_text = f"{pct:.2f}%" if isinstance(pct, (int, float)) else "—"
            lines.append(f"  · {label}: {item.get('pixel_count', 0)} 像素（{pct_text}）")
    else:
        lines.append("- 未识别到任何地物类别。")
    lines.append("解读边界: 模型基于 LandCover.ai 航拍数据集训练（建筑、林地、水体、背景四类），对中高分辨率光学航拍/卫星 RGB 影像效果最佳；分辨率或场景差异较大时结果仅供参考。")
    return "\n".join(lines)

from __future__ import annotations


MODE_LABELS = {
    "true_color": "真彩色",
    "false_color": "假彩色",
    "custom": "自定义波段组合",
}


def format_band_composite_context(imagery_id: str, mode: str, bands_used: list[int], result_filename: str) -> str:
    return "\n".join(
        [
            f"{MODE_LABELS.get(mode, mode)} 已生成（影像 ID: {imagery_id}）。",
            f"- 使用波段: {bands_used}",
            f"- 结果图层: {result_filename}",
            "说明: 该图层是可视化预览，不改变原始影像数据。",
        ]
    )

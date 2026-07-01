from __future__ import annotations

from typing import Any


def format_ocr_context(
    imagery_id: str,
    stats: dict[str, Any],
    *,
    max_chars: int,
) -> str:
    """把 OCR 结果格式化为 LLM 可读上下文：元信息摘要 + 全文（按 max_chars 截断）。"""
    full_text = str(stats.get("full_text") or "")
    block_count = int(stats.get("block_count") or 0)
    avg_conf = stats.get("avg_confidence")
    min_conf = stats.get("min_confidence_seen")
    grayscale = bool(stats.get("grayscale"))

    truncated = False
    shown = full_text
    if max_chars and len(full_text) > max_chars:
        shown = full_text[:max_chars]
        truncated = True

    header = [
        "## 影像文字识别（OCR）结果",
        "职责：只转述本次 OCR 真实识别到的文字，不补全、不脑补图面没有的内容。",
        "边界：OCR 为自动识别（RapidOCR / PP-OCRv4），可能存在错字、漏字、版面顺序错乱，"
        "尤其低分辨率、艺术字体、倾斜或污损文字；引用关键数字、地名、编号时提示可能的识别误差。",
        "",
        f"- 影像ID: {imagery_id}",
        f"- 识别文本块数: {block_count}",
        f"- 总字数: {len(full_text)}",
        f"- 识别模式: {'灰度' if grayscale else 'RGB'}",
    ]
    if avg_conf is not None:
        header.append(f"- 平均置信度: {avg_conf}")
    if min_conf is not None:
        header.append(f"- 最低置信度: {min_conf}")

    if block_count == 0:
        header.append("")
        header.append("本次未识别到任何文字。可能影像不含文字，或文字过小/模糊；"
                      "可尝试开启 grayscale、调整波段或提高 max_dimension 后重试。")
        return "\n".join(header)

    if truncated:
        header.append(f"- 注意: 全文较长，仅返回前 {max_chars} 字，结论请仅基于已返回部分，剩余内容未包含。")

    header.append("")
    header.append("--- 识别全文 ---")
    header.append(shown)
    return "\n".join(header)

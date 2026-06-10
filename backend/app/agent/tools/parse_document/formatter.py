from __future__ import annotations

from typing import Any


def format_parse_document_context(
    document_id: str,
    *,
    title: str,
    doc_type: str | None,
    metadata: dict[str, Any],
    content: str,
    truncated: bool,
    full_length: int,
) -> str:
    """Format full document text + metadata as LLM-readable context."""
    page_count = metadata.get("page_count")
    ocr_used = metadata.get("ocr_used")
    header = [
        "## 文档全文",
        "职责：基于下方文档全文回答用户的总结/抽取问题，只引用文中真实出现的内容，不编造。",
        "边界：本文档在上传时已解析入库，若解析自 PDF/扫描件，文本可能含 OCR 识别误差或版面错乱；"
        "引用关键数字/条款时保持谨慎。",
        "",
        f"- 文档ID: {document_id}",
        f"- 标题: {title}",
        f"- 类型: {doc_type or '未知'}",
    ]
    if page_count is not None:
        header.append(f"- 页数: {page_count}")
    if ocr_used:
        header.append("- 解析方式: 含 OCR（识别文本，可能有误差）")
    header.append(f"- 全文字数: {full_length}")
    if truncated:
        header.append(
            f"- 注意: 全文超出返回上限，以下仅为前 {len(content)} 字（已截断）。"
            "如需后续内容请缩小问题范围或分段询问。"
        )
    header.extend(["", "---", "", content])
    return "\n".join(header)

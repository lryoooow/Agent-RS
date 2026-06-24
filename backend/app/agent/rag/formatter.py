from __future__ import annotations

import json
from typing import Any


def format_retrieved_blocks(items: list[dict], *, title: str, content_key: str = "content") -> str:
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        content = str(item.get(content_key) or "").strip()
        if not content:
            continue
        score = item.get("rerank_score", item.get("score", item.get("vector_score")))
        score_text = f" score={float(score):.3f}" if isinstance(score, int | float) else ""
        # 章节归属：document 块入库时在 metadata.section 记录面包屑（如「第3章 › 3.1」），
        # 让模型知道该块在原文中的位置。memory 等无 section 的来源自然降级，块头不变。
        section = _section_label(item.get("metadata"))
        section_text = f" · {section}" if section else ""
        lines.append(f"[{title} {index}{section_text}{score_text}]\n{content}")
    return "\n\n".join(lines)


def _section_label(metadata: Any) -> str:
    """从块 metadata 提取章节面包屑；metadata 可能是 dict 或 jsonb 反序列化出的 str。"""
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            return ""
    if not isinstance(metadata, dict):
        return ""
    section = metadata.get("section")
    return section.strip() if isinstance(section, str) else ""

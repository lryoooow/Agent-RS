from __future__ import annotations


def format_retrieved_blocks(items: list[dict], *, title: str, content_key: str = "content") -> str:
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        content = str(item.get(content_key) or "").strip()
        if not content:
            continue
        score = item.get("rerank_score", item.get("score", item.get("vector_score")))
        score_text = f" score={float(score):.3f}" if isinstance(score, int | float) else ""
        lines.append(f"[{title} {index}{score_text}]\n{content}")
    return "\n\n".join(lines)

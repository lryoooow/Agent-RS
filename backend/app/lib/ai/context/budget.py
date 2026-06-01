TRUNCATION_MARKER = "\n...[context truncated]"


def trim_to_budget(content: str, max_chars: int | None) -> str:
    text = content.strip()
    if max_chars is None or len(text) <= max_chars:
        return text
    if max_chars <= 0:
        return ""

    if max_chars <= len(TRUNCATION_MARKER):
        return text[:max_chars].rstrip()

    return f"{text[: max_chars - len(TRUNCATION_MARKER)].rstrip()}{TRUNCATION_MARKER}"

import unicodedata


TRUNCATION_MARKER = "\n...[context truncated]"


def estimate_tokens(content: str) -> int:
    """Lightweight token estimate tuned for mixed Chinese/English text."""
    total = 0.0
    for char in content:
        if char.isspace():
            total += 0.1
        elif _is_cjk(char):
            total += 1.5
        elif char.isascii():
            total += 0.25
        else:
            total += 1.0
    return max(1, int(total + 0.999)) if content else 0


def trim_to_budget(content: str, max_tokens: int | None) -> str:
    text = content.strip()
    if max_tokens is None or estimate_tokens(text) <= max_tokens:
        return text
    if max_tokens <= 0:
        return ""

    marker_tokens = estimate_tokens(TRUNCATION_MARKER)
    if max_tokens <= marker_tokens:
        return _trim_text_to_tokens(text, max_tokens).rstrip()

    return f"{_trim_text_to_tokens(text, max_tokens - marker_tokens).rstrip()}{TRUNCATION_MARKER}"


def _trim_text_to_tokens(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    used = 0
    output: list[str] = []
    for char in text:
        char_tokens = estimate_tokens(char)
        if output and used + char_tokens > max_tokens:
            break
        output.append(char)
        used += char_tokens
    return "".join(output)


def _is_cjk(char: str) -> bool:
    name = unicodedata.name(char, "")
    return (
        "CJK UNIFIED" in name
        or "HIRAGANA" in name
        or "KATAKANA" in name
        or "HANGUL" in name
    )

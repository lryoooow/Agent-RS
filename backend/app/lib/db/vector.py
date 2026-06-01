from __future__ import annotations


def encode_vector(values: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.10g}" for value in values) + "]"


def decode_vector(value) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [float(item) for item in value]
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if not text.strip():
        return []
    try:
        return [float(item.strip()) for item in text.split(",") if item.strip()]
    except ValueError:
        return None

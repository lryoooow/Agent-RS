from __future__ import annotations

from typing import Any


def sanitize_text(value: str) -> str:
    return "".join(
        char
        for char in value
        if char == "\n" or char == "\t" or char == "\r" or ord(char) >= 32
    )


def sanitize_json(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [sanitize_json(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json(item) for item in value]
    if isinstance(value, dict):
        return {sanitize_text(str(key)): sanitize_json(item) for key, item in value.items()}
    return value

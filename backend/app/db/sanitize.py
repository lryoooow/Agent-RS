from __future__ import annotations

import json
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


def parse_jsonb(value: Any) -> dict[str, Any] | None:
    """把 asyncpg 读回的 jsonb 列归一成 dict|None。

    写入侧统一 `json.dumps(...)::jsonb`（见 memory/message repo），未注册 jsonb 解码 codec，
    故 asyncpg 读回的是 JSON 字符串——需在此显式 loads，否则上层 pydantic dict 校验 500。
    已是 dict（将来若注册 codec）则原样返回；空/非 dict 一律归 None，保证调用方拿到 dict|None。
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, (str, bytes)):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


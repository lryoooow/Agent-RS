from __future__ import annotations

import logging
import sys
from typing import Any

from app.core.settings import get_settings

SENSITIVE_KEY_PARTS = (
    "key",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
)

# Token *counts* are operational metrics, not credentials.  Substring matching
# previously redacted total_tokens/input_tokens, silently breaking usage logs.
SAFE_TOKEN_METRIC_KEYS = frozenset(
    {
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "prompt_tokens",
        "completion_tokens",
        "tokens_in",
        "tokens_out",
    }
)


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
            stream=sys.stdout,
            force=False,
        )
    logging.getLogger("app").setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    # AutoGen 的事件 logger 在 INFO 级别记录完整 LLM 请求、system prompt、历史消息、
    # reasoning/thought 与工具结果。这是敏感内容出口，生产和本地都必须默认封住。
    # 精确设置子 logger，避免第三方以后给它单独挂 handler 时绕过父级。
    for logger_name in (
        "autogen_core",
        "autogen_core.events",
        "autogen_core.trace",
        "autogen_agentchat",
        "autogen_agentchat.events",
    ):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def log_event(logger: logging.Logger, stage: str, **fields: Any) -> None:
    logger.info("[%s] %s", stage, " ".join(_format_field(key, value) for key, value in fields.items()))


def _format_field(key: str, value: Any) -> str:
    if _is_sensitive_key(key):
        value = "***"
    if isinstance(value, float):
        value = round(value, 4)
    text = str(value).replace("\n", "\\n")
    if not text or any(char.isspace() for char in text):
        text = '"' + text.replace('"', '\\"') + '"'
    return f"{key}={text}"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in SAFE_TOKEN_METRIC_KEYS:
        return False
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)

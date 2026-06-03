from __future__ import annotations

import logging
import sys
from typing import Any

from app.shared.settings import get_settings

SENSITIVE_KEY_PARTS = (
    "key",
    "token",
    "secret",
    "password",
    "authorization",
    "cookie",
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
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)

import logging

from app.core.logging import _format_field, configure_logging
from app.core.settings import get_settings


def test_autogen_sensitive_event_loggers_are_suppressed(monkeypatch, caplog) -> None:
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    get_settings.cache_clear()
    names = (
        "autogen_core",
        "autogen_core.events",
        "autogen_core.trace",
        "autogen_agentchat",
        "autogen_agentchat.events",
    )
    previous = {name: logging.getLogger(name).level for name in names}
    try:
        configure_logging()
        for name in names:
            assert logging.getLogger(name).level >= logging.WARNING

        secret = "RAW_REASONING_LOG_SECRET"
        logging.getLogger("autogen_core.events").info(secret)
        assert secret not in caplog.text
    finally:
        for name, level in previous.items():
            logging.getLogger(name).setLevel(level)
        get_settings.cache_clear()


def test_usage_token_counts_are_not_mistaken_for_credentials() -> None:
    assert _format_field("total_tokens", 321) == "total_tokens=321"
    assert _format_field("input_tokens", 123) == "input_tokens=123"
    assert _format_field("access_token", "secret") == "access_token=***"

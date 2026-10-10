from __future__ import annotations

import logging

from app.agent.errors import AuthError, ProviderError, map_provider_error
from app.core.error_logging import log_exception_diagnostics


def _captured_exception() -> RuntimeError:
    try:
        raise RuntimeError("api_key=TOP_SECRET user payload")
    except RuntimeError as exc:
        return exc


def test_exception_diagnostics_are_actionable_without_raw_message(caplog) -> None:
    caplog.set_level(logging.WARNING)
    fingerprint = log_exception_diagnostics(
        logging.getLogger("test.diagnostics"),
        "unit.failure",
        _captured_exception(),
        tool="segment_instances",
    )

    assert len(fingerprint) == 16
    assert "unit.failure" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "test_error_observability.py" in caplog.text
    assert "tool=segment_instances" in caplog.text
    assert "TOP_SECRET" not in caplog.text
    assert "user payload" not in caplog.text


def test_provider_mapping_logs_diagnostic_fingerprint_without_secret(caplog) -> None:
    caplog.set_level(logging.WARNING)
    mapped = map_provider_error(_captured_exception())

    assert isinstance(mapped, ProviderError)
    assert "ai.provider_error" in caplog.text
    assert "mapped_code=PROVIDER_ERROR" in caplog.text
    assert "TOP_SECRET" not in caplog.text


def test_provider_auth_error_is_actionable_and_localized(caplog) -> None:
    class AuthenticationError(RuntimeError):
        status_code = 401

    caplog.set_level(logging.WARNING)
    mapped = map_provider_error(AuthenticationError("api_key=TOP_SECRET"))

    assert isinstance(mapped, AuthError)
    assert mapped.status_code == 401
    assert "认证失败" in mapped.message
    assert "配置" in mapped.message
    assert "API Key" in mapped.message
    assert "TOP_SECRET" not in caplog.text

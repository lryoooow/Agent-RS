from __future__ import annotations

import pytest

from app.auth.rate_limit import AuthRateLimiter


def limiter(**overrides) -> AuthRateLimiter:
    values = {
        "max_failures": 2,
        "failure_window_seconds": 60,
        "lockout_seconds": 30,
        "login_ip_max_attempts": 3,
        "login_ip_window_seconds": 60,
        "register_ip_max_attempts": 2,
        "register_ip_window_seconds": 60,
        "max_entries": 128,
    }
    values.update(overrides)
    return AuthRateLimiter(**values)


@pytest.mark.asyncio
async def test_failed_account_is_locked_and_success_clears_state() -> None:
    guard = limiter()
    assert await guard.check_login(account_key="user@example.com", client_key="ip-1") is None
    assert await guard.record_login_failure(account_key="user@example.com") is None
    assert await guard.record_login_failure(account_key="user@example.com") == 30
    assert await guard.check_login(account_key="user@example.com", client_key="ip-2") == 30
    await guard.record_login_success(account_key="user@example.com")
    assert await guard.check_login(account_key="user@example.com", client_key="ip-2") is None


@pytest.mark.asyncio
async def test_login_ip_window_blocks_before_extra_pbkdf2_work() -> None:
    guard = limiter()
    for account in ("a@example.com", "b@example.com", "c@example.com"):
        assert await guard.check_login(account_key=account, client_key="shared-ip") is None
    assert await guard.check_login(account_key="d@example.com", client_key="shared-ip") == 60


@pytest.mark.asyncio
async def test_registration_has_independent_ip_limit() -> None:
    guard = limiter()
    assert await guard.check_register(client_key="registration-ip") is None
    assert await guard.check_register(client_key="registration-ip") is None
    assert await guard.check_register(client_key="registration-ip") == 60

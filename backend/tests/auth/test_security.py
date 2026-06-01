import pytest

from app.lib.auth.current_user import get_current_user_id, reset_current_user_id, set_current_user_id
from app.lib.auth.security import hash_password, hash_session_token, verify_password
from app.shared.settings import get_settings


@pytest.mark.asyncio
async def test_password_hash_verification_round_trip() -> None:
    password_hash = await hash_password("correct horse battery staple")

    assert await verify_password("correct horse battery staple", password_hash)
    assert not await verify_password("wrong password", password_hash)


def test_session_token_hash_uses_secret_key() -> None:
    token = "session-token"

    assert hash_session_token(token, "secret-a") == hash_session_token(token, "secret-a")
    assert hash_session_token(token, "secret-a") != hash_session_token(token, "secret-b")


def test_current_user_context_falls_back_to_default() -> None:
    get_settings.cache_clear()
    assert get_current_user_id() == get_settings().default_user_id

    token = set_current_user_id("00000000-0000-4000-8000-000000000123")
    try:
        assert get_current_user_id() == "00000000-0000-4000-8000-000000000123"
    finally:
        reset_current_user_id(token)

    assert get_current_user_id() == get_settings().default_user_id

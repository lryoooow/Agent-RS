import pytest
from fastapi.testclient import TestClient

from app.auth.current_user import get_current_user_id, reset_current_user_id, set_current_user_id
from app.auth.security import hash_password, hash_session_token, verify_password
from app.auth.session import AuthSessionUnavailable, get_session_user
from app.core.settings import get_settings
from app.main import create_app


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


@pytest.mark.asyncio
async def test_session_user_raises_when_token_cannot_be_checked(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    get_settings.cache_clear()

    async def fake_fetch_optional_pool():
        return None

    monkeypatch.setattr("app.auth.session.fetch_optional_pool", fake_fetch_optional_pool)

    with pytest.raises(AuthSessionUnavailable):
        await get_session_user("session-token")


def test_session_db_unavailable_returns_503_instead_of_default_user(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    get_settings.cache_clear()

    async def fake_fetch_optional_pool():
        return None

    monkeypatch.setattr("app.auth.session.fetch_optional_pool", fake_fetch_optional_pool)
    client = TestClient(create_app())

    response = client.get("/api/auth/me", cookies={get_settings().auth_session_cookie_name: "session-token"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AUTH_SESSION_UNAVAILABLE"


def test_auth_routes_reject_default_secret_when_database_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("AUTH_SECRET_KEY", "dev-change-me")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.post("/api/auth/login", json={"email": "user@example.com", "password": "password123"})

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "AUTH_SECRET_INSECURE"

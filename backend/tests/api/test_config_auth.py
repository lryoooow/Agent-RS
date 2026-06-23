from fastapi.testclient import TestClient

from app.main import create_app
from app.core.settings import get_settings


def make_client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


def test_config_exposes_auth_required_and_invite_required(monkeypatch) -> None:
    # auth_required = auth_enabled AND database_enabled
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("INVITE_REQUIRED", "true")
    client = make_client()

    body = client.get("/api/config").json()
    assert body["auth_required"] is True
    assert body["invite_required"] is True


def test_config_auth_not_required_when_db_disabled(monkeypatch) -> None:
    # 本地 DB 关闭：保留默认用户兜底，前端不应强制登录。
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    client = make_client()

    body = client.get("/api/config").json()
    assert body["auth_required"] is False


def test_config_auth_not_required_when_auth_disabled(monkeypatch) -> None:
    monkeypatch.setenv("AUTH_ENABLED", "false")
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    client = make_client()

    body = client.get("/api/config").json()
    assert body["auth_required"] is False

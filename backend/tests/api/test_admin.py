from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.deps import require_admin
from app.auth import user_scope
from app.core.settings import Settings


class Pool:
    def acquire(self):
        return self

    async def __aenter__(self):
        return object()

    async def __aexit__(self, *args):
        return False


def configure(monkeypatch, *, enabled=True, admins=" admin-1, admin-2 ", user=None):
    settings = Settings(_env_file=None, auth_enabled=enabled, database_enabled=True, auth_admin_user_ids=admins)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: settings)
    lookup = AsyncMock(return_value=user)
    monkeypatch.setattr("app.api.deps.get_user_by_id", lookup)
    monkeypatch.setattr("app.api.deps.fetch_optional_pool", AsyncMock(return_value=Pool()))
    return settings, lookup


@pytest.mark.asyncio
async def test_configured_active_admin_is_authorized(monkeypatch):
    _, lookup = configure(monkeypatch, user={"id": "admin-1", "is_active": True, "email": "unverified@example.com"})
    with user_scope("admin-1"):
        assert (await require_admin())["id"] == "admin-1"
    lookup.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("user_id", [None, "ordinary-user"])
async def test_anonymous_and_unconfigured_users_are_rejected_before_database_lookup(monkeypatch, user_id):
    _, lookup = configure(monkeypatch, user={"id": "ordinary-user", "is_active": True, "email": "admin@example.com"})
    with user_scope(user_id), pytest.raises(HTTPException) as error:
        await require_admin()
    assert error.value.status_code == (401 if user_id is None else 403)
    lookup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("user", [None, {"id": "admin-1", "is_active": False}])
async def test_deleted_or_disabled_admin_is_rejected(monkeypatch, user):
    configure(monkeypatch, user=user)
    with user_scope("admin-1"), pytest.raises(HTTPException) as error:
        await require_admin()
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_auth_disabled_never_grants_anonymous_administration(monkeypatch):
    settings, lookup = configure(monkeypatch, enabled=False)
    settings.auth_admin_user_ids = settings.default_user_id
    with user_scope(None), pytest.raises(HTTPException) as error:
        await require_admin()
    assert error.value.status_code == 403
    lookup.assert_not_awaited()


def test_empty_administrator_configuration_grants_no_privileges():
    assert not Settings(_env_file=None, auth_admin_user_ids="").is_admin_user_id("admin-1")

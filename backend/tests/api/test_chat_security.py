from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.errors import ConversationAccessError, PersistenceUnavailableError
from app.api.routes.chat import _authorize_requested_conversation


class _Acquire:
    def __init__(self, conn: object) -> None:
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, *_exc):
        return False


class _Pool:
    def acquire(self):
        return _Acquire(object())


@pytest.mark.asyncio
async def test_chat_preflight_rejects_foreign_or_missing_conversation(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.chat.get_settings",
        lambda: SimpleNamespace(storage_active=True),
    )
    monkeypatch.setattr(
        "app.api.routes.chat.fetch_optional_pool",
        AsyncMock(return_value=_Pool()),
    )
    lookup = AsyncMock(return_value=None)
    monkeypatch.setattr("app.api.routes.chat.get_conversation", lookup)

    with pytest.raises(ConversationAccessError):
        await _authorize_requested_conversation(
            "00000000-0000-4000-8000-000000000301",
            user_id="00000000-0000-4000-8000-000000000001",
        )

    lookup.assert_awaited_once()


@pytest.mark.asyncio
async def test_chat_preflight_uses_same_error_for_malformed_identifier(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.chat.get_settings",
        lambda: SimpleNamespace(storage_active=True),
    )

    with pytest.raises(ConversationAccessError) as exc_info:
        await _authorize_requested_conversation("not-a-uuid", user_id="user")

    assert exc_info.value.code == "CONVERSATION_NOT_FOUND"
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_chat_preflight_fails_closed_when_database_is_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.chat.get_settings",
        lambda: SimpleNamespace(storage_active=True),
    )
    monkeypatch.setattr(
        "app.api.routes.chat.fetch_optional_pool",
        AsyncMock(return_value=None),
    )

    with pytest.raises(PersistenceUnavailableError):
        await _authorize_requested_conversation(
            "00000000-0000-4000-8000-000000000301",
            user_id="00000000-0000-4000-8000-000000000001",
        )

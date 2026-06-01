from __future__ import annotations

from contextvars import ContextVar, Token

from app.shared.settings import get_settings

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def get_current_user_id() -> str:
    return _current_user_id.get() or get_settings().default_user_id


def set_current_user_id(user_id: str | None) -> Token[str | None]:
    return _current_user_id.set(user_id)


def reset_current_user_id(token: Token[str | None]) -> None:
    _current_user_id.reset(token)

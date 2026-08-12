from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from app.core.settings import get_settings

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def get_current_user_id() -> str:
    return _current_user_id.get() or get_settings().default_user_id


def peek_current_user_id() -> str | None:
    """取当前用户 ID，**不回退到 default_user_id**。

    鉴权路径必须用这个而不是 get_current_user_id()：后者在未设置时会回退成默认用户，
    对「有没有登录身份」这个判断来说，等于把匿名请求当默认用户放行。
    tool_guards 依赖 user_id 为 None 时返回 owner_required，所以不能吃到那个回退值。
    """
    return _current_user_id.get()


def set_current_user_id(user_id: str | None) -> Token[str | None]:
    return _current_user_id.set(user_id)


def reset_current_user_id(token: Token[str | None]) -> None:
    _current_user_id.reset(token)


@contextmanager
def user_scope(user_id: str | None) -> Iterator[str | None]:
    """在一段作用域内绑定当前用户，**按值恢复而不是用 Token**。

    async generator（流式 SSE 链路）每次恢复运行在不同 Context 中，
    `ContextVar.reset(token)` 会抛 `ValueError: ... created in a different Context`。
    实测该异常发生在 finally 里，会把整个流式响应变成 error 事件。
    `set()` 无此限制，故按值存取。
    """
    previous = _current_user_id.get()
    _current_user_id.set(user_id)
    try:
        yield user_id
    finally:
        _current_user_id.set(previous)

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

# 当前请求的对话 ID（请求级 contextvar，镜像 current_user）。
# 工具 runner 的签名固定为 (args)->ToolRunResult，不接收 conversation_id；
# generate_report 这类需要"读本对话历史结果"的工具，经此 contextvar 在同一执行链内取值，
# AIService 以持久化层确认的会话 ID 绑定，工具参数不能自行指定会话。
_current_conversation_id: ContextVar[str | None] = ContextVar(
    "current_conversation_id", default=None
)


def get_current_conversation_id() -> str | None:
    return _current_conversation_id.get()


def set_current_conversation_id(conversation_id: str | None) -> Token[str | None]:
    return _current_conversation_id.set(conversation_id)


def reset_current_conversation_id(token: Token[str | None]) -> None:
    _current_conversation_id.reset(token)


@contextmanager
def conversation_scope(conversation_id: str | None) -> Iterator[str | None]:
    """Bind a verified conversation for a turn, including child tool tasks.

    Restore by value, like user_scope: SSE generators may be closed in a
    different Context, where resetting a ContextVar token would raise.
    """
    previous = _current_conversation_id.get()
    _current_conversation_id.set(conversation_id)
    try:
        yield conversation_id
    finally:
        _current_conversation_id.set(previous)

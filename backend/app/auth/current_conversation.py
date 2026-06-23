from __future__ import annotations

from contextvars import ContextVar, Token

# 当前请求的对话 ID（请求级 contextvar，镜像 current_user）。
# 工具 runner 的签名固定为 (args)->ToolRunResult，不接收 conversation_id；
# generate_report 这类需要"读本对话历史结果"的工具，经此 contextvar 在同一执行链内取值，
# 避免改动 11 个已验证 runner 的签名。runtime.plan() 顶部按 request.conversation_id set。
_current_conversation_id: ContextVar[str | None] = ContextVar(
    "current_conversation_id", default=None
)


def get_current_conversation_id() -> str | None:
    return _current_conversation_id.get()


def set_current_conversation_id(conversation_id: str | None) -> Token[str | None]:
    return _current_conversation_id.set(conversation_id)


def reset_current_conversation_id(token: Token[str | None]) -> None:
    _current_conversation_id.reset(token)

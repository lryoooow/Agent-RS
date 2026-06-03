from typing import Any

from app.agent.config import ResolvedAIConfig
from app.agent.reasoning import split_think_blocks
from app.schemas.chat import ChatResponse, Usage


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def normalize_chat_response(response: Any, config: ResolvedAIConfig) -> ChatResponse:
    choices = _read(response, "choices", []) or []
    first_choice = choices[0] if choices else None
    message = _read(first_choice, "message", {}) if first_choice else {}
    content = _read(message, "content", "") or ""
    _, content = split_think_blocks(content)
    usage = _read(response, "usage", None)

    normalized_usage = None
    if usage is not None:
        normalized_usage = Usage(
            input_tokens=_read(usage, "prompt_tokens", None),
            output_tokens=_read(usage, "completion_tokens", None),
            total_tokens=_read(usage, "total_tokens", None),
        )

    return ChatResponse(
        content=content,
        model=_read(response, "model", None) or config.model,
        provider=config.provider,
        usage=normalized_usage,
        finish_reason=_read(first_choice, "finish_reason", None) if first_choice else None,
    )

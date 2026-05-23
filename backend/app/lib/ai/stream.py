import json
from typing import Any, AsyncIterator

from app.lib.ai.config import ResolvedAIConfig
from app.lib.ai.errors import AIError, map_provider_error
from app.lib.ai.reasoning import ThinkTagParser
from app.schemas.chat import Usage

REASONING_FIELDS = ("reasoning_content", "reasoning", "thinking", "thought")


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _normalize_usage(usage: Any) -> dict[str, int | None] | None:
    if usage is None:
        return None
    normalized = Usage(
        input_tokens=_read(usage, "prompt_tokens", None),
        output_tokens=_read(usage, "completion_tokens", None),
        total_tokens=_read(usage, "total_tokens", None),
    )
    return normalized.model_dump(exclude_none=True)


def normalize_stream_chunk(chunk: Any) -> dict[str, Any]:
    choices = _read(chunk, "choices", []) or []
    first_choice = choices[0] if choices else None
    delta = _read(first_choice, "delta", {}) if first_choice else {}
    reasoning = next((_read(delta, field, None) for field in REASONING_FIELDS if _read(delta, field, None)), None)

    return {
        "content": _read(delta, "content", None),
        "reasoning": reasoning,
        "finish_reason": _read(first_choice, "finish_reason", None) if first_choice else None,
        "usage": _normalize_usage(_read(chunk, "usage", None)),
    }


async def stream_sse_events(stream: AsyncIterator[Any], config: ResolvedAIConfig) -> AsyncIterator[str]:
    yield sse_event("meta", {"model": config.model, "provider": config.provider})

    finish_reason: str | None = None
    usage: dict[str, int | None] | None = None
    think_parser = ThinkTagParser()

    try:
        async for chunk in stream:
            normalized = normalize_stream_chunk(chunk)
            reasoning = normalized["reasoning"]
            content = normalized["content"]

            if reasoning:
                yield sse_event("reasoning_delta", {"content": reasoning})

            if content:
                for channel, value in think_parser.feed(content):
                    event = "reasoning_delta" if channel == "reasoning" else "delta"
                    yield sse_event(event, {"content": value})

            if normalized["finish_reason"]:
                finish_reason = normalized["finish_reason"]
            if normalized["usage"]:
                usage = normalized["usage"]
    except Exception as exc:
        error = exc if isinstance(exc, AIError) else map_provider_error(exc)
        yield sse_event("error", {"code": error.code, "message": error.message})
        return

    for channel, value in think_parser.flush():
        event = "reasoning_delta" if channel == "reasoning" else "delta"
        yield sse_event(event, {"content": value})

    done_payload: dict[str, Any] = {"finish_reason": finish_reason}
    if usage:
        done_payload["usage"] = usage
    yield sse_event("done", done_payload)

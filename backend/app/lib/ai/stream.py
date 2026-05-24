import asyncio
import json
from typing import Any, AsyncIterator, Iterator

from app.lib.ai.config import ResolvedAIConfig
from app.lib.ai.errors import AIError, map_provider_error
from app.lib.ai.reasoning import ThinkTagParser
from app.schemas.chat import Usage

REASONING_FIELDS = ("reasoning_content", "reasoning", "thinking", "thought")
ANALYSIS_STATUS_PAUSE_SECONDS = 0.12
ANSWER_DELTA_PAUSE_SECONDS = 0.025
ANSWER_DELTA_MAX_CHARS = 8
ANALYSIS_STATUS_LABELS = {
    "analyzing": "正在分析问题…",
    "preparing": "正在整理内容…",
    "answering": "正在组织回复…",
    "complete": "思考完成",
}


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def analysis_status_event(status: str) -> str:
    return sse_event(
        "analysis_status",
        {
            "status": status,
            "label": ANALYSIS_STATUS_LABELS[status],
        },
    )


def iter_answer_delta_parts(content_buffer: list[str]) -> Iterator[str]:
    for value in content_buffer:
        if not value:
            continue
        for cursor in range(0, len(value), ANSWER_DELTA_MAX_CHARS):
            part = value[cursor : cursor + ANSWER_DELTA_MAX_CHARS]
            if part:
                yield part


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
    yield analysis_status_event("analyzing")
    await asyncio.sleep(ANALYSIS_STATUS_PAUSE_SECONDS)
    yield analysis_status_event("preparing")
    await asyncio.sleep(ANALYSIS_STATUS_PAUSE_SECONDS)
    yield analysis_status_event("answering")

    finish_reason: str | None = None
    usage: dict[str, int | None] | None = None
    think_parser = ThinkTagParser()
    content_buffer: list[str] = []

    try:
        async for chunk in stream:
            normalized = normalize_stream_chunk(chunk)
            content = normalized["content"]

            if content:
                for channel, value in think_parser.feed(content):
                    if channel == "reasoning":
                        continue
                    content_buffer.append(value)

            if normalized["finish_reason"]:
                finish_reason = normalized["finish_reason"]
            if normalized["usage"]:
                usage = normalized["usage"]
    except Exception as exc:
        error = exc if isinstance(exc, AIError) else map_provider_error(exc)
        yield sse_event("error", {"code": error.code, "message": error.message})
        return

    for channel, value in think_parser.flush():
        if channel == "reasoning":
            continue
        content_buffer.append(value)

    done_payload: dict[str, Any] = {"finish_reason": finish_reason}
    if usage:
        done_payload["usage"] = usage
    yield analysis_status_event("complete")
    answer_parts = list(iter_answer_delta_parts(content_buffer))
    if answer_parts:
        await asyncio.sleep(ANALYSIS_STATUS_PAUSE_SECONDS)
    for index, value in enumerate(answer_parts):
        yield sse_event("delta", {"content": value})
        if index < len(answer_parts) - 1:
            await asyncio.sleep(ANSWER_DELTA_PAUSE_SECONDS)
    yield sse_event("done", done_payload)

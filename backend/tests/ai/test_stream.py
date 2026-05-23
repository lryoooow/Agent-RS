from types import SimpleNamespace

import pytest

from app.lib.ai.config import ResolvedAIConfig
from app.lib.ai.stream import normalize_stream_chunk, stream_sse_events


def make_config() -> ResolvedAIConfig:
    return ResolvedAIConfig(
        provider="openai-compatible",
        base_url="https://example.com/v1",
        api_key="secret",
        model="stream-model",
        timeout_seconds=60,
        max_retries=2,
        trust_env_proxy=False,
    )


async def fake_stream():
    yield SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="你"),
                finish_reason=None,
            )
        ],
        usage=None,
    )
    yield SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="好"),
                finish_reason=None,
            )
        ],
        usage=None,
    )
    yield SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
    )


def test_normalize_stream_chunk_reads_delta_content() -> None:
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="hello"),
                finish_reason=None,
            )
        ],
        usage=None,
    )

    result = normalize_stream_chunk(chunk)

    assert result["content"] == "hello"
    assert result["reasoning"] is None
    assert result["finish_reason"] is None
    assert result["usage"] is None


def test_normalize_stream_chunk_reads_reasoning_content() -> None:
    chunk = SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=None, reasoning_content="thinking"),
                finish_reason=None,
            )
        ],
        usage=None,
    )

    result = normalize_stream_chunk(chunk)

    assert result["reasoning"] == "thinking"
    assert result["content"] is None


@pytest.mark.asyncio
async def test_stream_sse_events_outputs_meta_delta_done() -> None:
    events = [event async for event in stream_sse_events(fake_stream(), make_config())]

    assert events[0] == 'event: meta\ndata: {"model": "stream-model", "provider": "openai-compatible"}\n\n'
    assert events[1] == 'event: delta\ndata: {"content": "你"}\n\n'
    assert events[2] == 'event: delta\ndata: {"content": "好"}\n\n'
    assert events[3] == (
        'event: done\ndata: {"finish_reason": "stop", '
        '"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}\n\n'
    )


@pytest.mark.asyncio
async def test_stream_sse_events_outputs_reasoning_delta() -> None:
    async def stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content=None, reasoning_content="thinking"),
                    finish_reason=None,
                )
            ],
            usage=None,
        )

    events = [event async for event in stream_sse_events(stream(), make_config())]

    assert events[0] == 'event: meta\ndata: {"model": "stream-model", "provider": "openai-compatible"}\n\n'
    assert events[1] == 'event: reasoning_delta\ndata: {"content": "thinking"}\n\n'
    assert events[2] == 'event: done\ndata: {"finish_reason": null}\n\n'


@pytest.mark.asyncio
async def test_stream_sse_events_splits_think_tags_across_chunks() -> None:
    async def stream():
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="<thi"), finish_reason=None)],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="nk>reason</thi"), finish_reason=None)],
            usage=None,
        )
        yield SimpleNamespace(
            choices=[SimpleNamespace(delta=SimpleNamespace(content="nk>answer"), finish_reason="stop")],
            usage=None,
        )

    events = [event async for event in stream_sse_events(stream(), make_config())]

    assert events[1] == 'event: reasoning_delta\ndata: {"content": "reason"}\n\n'
    assert events[2] == 'event: delta\ndata: {"content": "answer"}\n\n'
    assert events[3] == 'event: done\ndata: {"finish_reason": "stop"}\n\n'

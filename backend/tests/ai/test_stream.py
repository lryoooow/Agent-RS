from types import SimpleNamespace

import pytest

from app.lib.ai.config import ResolvedAIConfig
from app.lib.ai.stream import normalize_stream_chunk, stream_initial_sse_events, stream_sse_events


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
async def test_stream_initial_sse_events_outputs_meta_and_statuses() -> None:
    events = [event async for event in stream_initial_sse_events(make_config())]

    assert events[0] == 'event: meta\ndata: {"model": "stream-model", "provider": "openai-compatible"}\n\n'
    assert events[1] == 'event: analysis_status\ndata: {"status": "analyzing", "label": "正在解析问题…"}\n\n'
    assert events[2] == 'event: analysis_status\ndata: {"status": "preparing", "label": "正在整理内容…"}\n\n'
    assert events[3] == 'event: analysis_status\ndata: {"status": "answering", "label": "正在组织回复…"}\n\n'


@pytest.mark.asyncio
async def test_stream_sse_events_outputs_complete_delta_done() -> None:
    events = [event async for event in stream_sse_events(fake_stream())]

    assert events[0] == 'event: analysis_status\ndata: {"status": "complete", "label": "思考完成"}\n\n'
    assert events[1] == 'event: delta\ndata: {"content": "你"}\n\n'
    assert events[2] == 'event: delta\ndata: {"content": "好"}\n\n'
    assert events[3] == (
        'event: done\ndata: {"finish_reason": "stop", '
        '"usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}\n\n'
    )


@pytest.mark.asyncio
async def test_stream_sse_events_suppresses_raw_reasoning_event() -> None:
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

    events = [event async for event in stream_sse_events(stream())]

    assert events[0] == 'event: analysis_status\ndata: {"status": "complete", "label": "思考完成"}\n\n'
    assert events[1] == 'event: done\ndata: {"finish_reason": null}\n\n'
    raw_reasoning_event = "reasoning" + "_delta"
    assert all(raw_reasoning_event not in event for event in events)
    assert all("thinking" not in event for event in events)


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

    events = [event async for event in stream_sse_events(stream())]

    assert events[0] == 'event: analysis_status\ndata: {"status": "complete", "label": "思考完成"}\n\n'
    assert events[1] == 'event: delta\ndata: {"content": "answer"}\n\n'
    assert events[2] == 'event: done\ndata: {"finish_reason": "stop"}\n\n'
    assert all('"content": "reason"' not in event for event in events)


@pytest.mark.asyncio
async def test_stream_sse_events_replays_long_answer_as_multiple_deltas_after_completion() -> None:
    async def stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="abcdefghijklmnop"),
                    finish_reason="stop",
                )
            ],
            usage=None,
        )

    events = [event async for event in stream_sse_events(stream())]
    complete_index = events.index('event: analysis_status\ndata: {"status": "complete", "label": "思考完成"}\n\n')
    delta_events = [event for event in events if event.startswith("event: delta\n")]
    first_delta_index = events.index(delta_events[0])

    assert complete_index < first_delta_index
    assert delta_events == [
        'event: delta\ndata: {"content": "abcdefgh"}\n\n',
        'event: delta\ndata: {"content": "ijklmnop"}\n\n',
    ]
    assert "".join(event.split('"content": "')[1].split('"')[0] for event in delta_events) == "abcdefghijklmnop"


@pytest.mark.asyncio
async def test_stream_sse_events_converts_error_after_visible_delta_to_done() -> None:
    async def stream():
        yield SimpleNamespace(
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="partial answer"),
                    finish_reason=None,
                )
            ],
            usage=None,
        )
        raise RuntimeError("provider broke")

    events = [event async for event in stream_sse_events(stream())]

    assert events[0] == 'event: analysis_status\ndata: {"status": "complete", "label": "思考完成"}\n\n'
    assert events[1] == 'event: delta\ndata: {"content": "partial "}\n\n'
    assert events[2] == 'event: delta\ndata: {"content": "answer"}\n\n'
    assert events[3] == (
        'event: done\ndata: {"finish_reason": "error", '
        '"error": {"code": "PROVIDER_ERROR", "message": "AI provider request failed."}}\n\n'
    )

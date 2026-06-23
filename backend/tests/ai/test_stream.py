from types import SimpleNamespace

import json

import pytest

from app.agent.config import ResolvedAIConfig
from app.agent.stream import (
    agent_status_event,
    normalize_stream_chunk,
    stream_initial_sse_events,
    stream_sse_events,
)


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
    assert events[1] == 'event: analysis_status\ndata: {"status": "analyzing", "label": "正在思考中…"}\n\n'
    assert events[2] == 'event: analysis_status\ndata: {"status": "preparing", "label": "正在梳理结果…"}\n\n'
    assert events[3] == 'event: analysis_status\ndata: {"status": "answering", "label": "正在生成回复…"}\n\n'


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


# ---------- agent_status_event：label 透传根因防回归 ----------


def _agent_status_payload(event: str) -> dict:
    # event 形如 'event: agent_status\ndata: {...}\n\n'，取出 data 行解析。
    for line in event.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"no data line in event: {event!r}")


def test_agent_status_event_uses_explicit_label_over_static_dict() -> None:
    # 根因：执行阶段具体工具名在 AgentEvent.label 里，必须透传到 SSE，
    # 不能被 AGENT_STATUS_LABELS 按 status 重新查回宽泛的"正在执行工具"。
    event = agent_status_event("child_agent_running", label="正在进行地物分类")
    payload = _agent_status_payload(event)
    assert payload["status"] == "child_agent_running"
    assert payload["label"] == "正在进行地物分类"
    # 关键：绝不能再退回宽泛标签。
    assert payload["label"] != "正在执行工具"


def test_agent_status_event_preserves_metadata_and_elapsed() -> None:
    # 常规：tool_name 等 metadata 与 elapsed_ms 原样进入 payload，不丢字段。
    event = agent_status_event(
        "child_agent_running",
        label="正在计算 NDVI",
        tool_name="calculate_ndvi",
        elapsed_ms=1234,
    )
    payload = _agent_status_payload(event)
    assert payload["tool_name"] == "calculate_ndvi"
    assert payload["elapsed_ms"] == 1234
    assert payload["label"] == "正在计算 NDVI"


def test_agent_status_event_falls_back_to_static_label_when_absent() -> None:
    # 边界：不传 label 时，已登记 status 回退到静态字典文案。
    event = agent_status_event("tool_execution_completed")
    payload = _agent_status_payload(event)
    assert payload["label"] == "工具执行完成"


def test_agent_status_event_unknown_status_falls_back_to_status_string() -> None:
    # 边界：未登记 status 且无 label → 回退为 status 本身，不崩、不抛。
    event = agent_status_event("some_unregistered_stage")
    payload = _agent_status_payload(event)
    assert payload["status"] == "some_unregistered_stage"
    assert payload["label"] == "some_unregistered_stage"

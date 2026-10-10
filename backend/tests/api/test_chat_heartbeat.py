from __future__ import annotations

import asyncio
from contextvars import ContextVar

import pytest

from app.agent.engine.turn_context import current_turn_state, turn_scope
from app.agent.search.credentials import resolve_tavily_api_key, tavily_key_scope
from app.api.routes.chat import stream_with_heartbeat
from app.auth.current_conversation import conversation_scope, get_current_conversation_id
from app.auth.current_user import peek_current_user_id, user_scope


@pytest.fixture(autouse=True)
def _isolated_search_key(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-server-search-key")


async def _request_source(owner, observations, *, pause=None):
    roi = [114.0, 24.0, 114.1, 24.1]
    with (
        user_scope(owner),
        conversation_scope(f"conversation-{owner}"),
        tavily_key_scope(f"test-search-{owner}"),
        turn_scope(trusted_tool_arguments={"segment_instances": {"bbox": roi}}) as state,
    ):
        assert state.try_reserve("segment_instances")
        for i in range(3):
            if pause is not None and i == 1:
                await pause.wait()
            await asyncio.sleep(0)
            current = current_turn_state()
            observations.append(
                (
                    peek_current_user_id(),
                    get_current_conversation_id(),
                    resolve_tavily_api_key() == f"test-search-{owner}",
                    current is state,
                    current.arguments_for("segment_instances", {"bbox": [0, 0, 1, 1]})
                    if current else None,
                    current.available("segment_instances") if current else None,
                )
            )
            yield f"event: delta\ndata: {owner}-{i}\n\n"


def _assert_request_state(owner, observations):
    assert observations == [
        (
            owner,
            f"conversation-{owner}",
            True,
            True,
            {"bbox": [114.0, 24.0, 114.1, 24.1]},
            False,
        )
    ] * 3


@pytest.mark.asyncio
async def test_request_scopes_and_roi_quota_survive_all_chunks(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_GPU_TOOL_CALLS", "1")
    observations = []
    with user_scope("caller"), conversation_scope("caller-conversation"), tavily_key_scope("test-caller"):
        chunks = [
            chunk async for chunk in stream_with_heartbeat(_request_source("a", observations))
        ]
        assert peek_current_user_id() == "caller"
        assert get_current_conversation_id() == "caller-conversation"
        assert resolve_tavily_api_key() == "test-caller"
        assert current_turn_state() is None
    assert len(chunks) == 3
    _assert_request_state("a", observations)


@pytest.mark.asyncio
async def test_context_survives_multiple_heartbeats_without_advancing_source(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_GPU_TOOL_CALLS", "1")
    pause = asyncio.Event()
    observations = []
    stream = stream_with_heartbeat(_request_source("a", observations, pause=pause), interval_seconds=0.001)
    try:
        assert "a-0" in await anext(stream)
        for _ in range(2):
            assert await asyncio.wait_for(anext(stream), 1) == ": keepalive\n\n"
        assert len(observations) == 1
        pause.set()
        remaining = [chunk async for chunk in stream]
        assert [chunk for chunk in remaining if not chunk.startswith(":")] == [
            "event: delta\ndata: a-1\n\n", "event: delta\ndata: a-2\n\n"
        ]
        _assert_request_state("a", observations)
    finally:
        await stream.aclose()


@pytest.mark.asyncio
async def test_concurrent_streams_do_not_share_scopes_or_quota(monkeypatch):
    monkeypatch.setenv("AGENT_MAX_GPU_TOOL_CALLS", "1")

    async def consume(owner):
        observations = []
        chunks = [chunk async for chunk in stream_with_heartbeat(_request_source(owner, observations))]
        _assert_request_state(owner, observations)
        assert all(f"{owner}-" in chunk for chunk in chunks)

    await asyncio.gather(consume("a"), consume("b"))
    assert peek_current_user_id() is None
    assert get_current_conversation_id() is None
    assert current_turn_state() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [False, True])
async def test_source_closes_in_its_context_after_eof_or_error(fail):
    marker = ContextVar("heartbeat-test-marker", default="caller")
    closed = []

    async def source():
        token = marker.set("source")
        try:
            yield "first"
            assert marker.get() == "source"
            if fail:
                raise RuntimeError("source-error")
        finally:
            closed.append(marker.get())
            marker.reset(token)

    stream = stream_with_heartbeat(source())
    assert await anext(stream) == "first"
    with pytest.raises(RuntimeError if fail else StopAsyncIteration):
        await anext(stream)
    assert closed == ["source"]
    assert marker.get() == "caller"


@pytest.mark.asyncio
async def test_early_close_after_yield_uses_source_context():
    marker = ContextVar("heartbeat-close-marker", default="caller")
    closed = []

    async def source():
        token = marker.set("source")
        try:
            yield "first"
            pytest.fail("Closing must not request the next business step")
        finally:
            closed.append(marker.get())
            marker.reset(token)

    stream = stream_with_heartbeat(source())
    assert await anext(stream) == "first"
    await stream.aclose()
    assert closed == ["source"]
    assert marker.get() == "caller"


@pytest.mark.asyncio
async def test_cancel_pending_read_closes_source_and_leaves_no_reader():
    marker = ContextVar("heartbeat-cancel-marker", default="caller")
    started = asyncio.Event()
    closed = asyncio.Event()

    async def source():
        token = marker.set("source")
        try:
            yield "first"
            started.set()
            await asyncio.Event().wait()
        finally:
            assert marker.get() == "source"
            marker.reset(token)
            closed.set()

    before = set(asyncio.all_tasks())
    stream = stream_with_heartbeat(source())
    assert await anext(stream) == "first"
    reader = asyncio.create_task(anext(stream))
    await asyncio.wait_for(started.wait(), 1)
    reader.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(reader, 1)
    await stream.aclose()
    assert closed.is_set()
    assert marker.get() == "caller"
    assert not [task for task in asyncio.all_tasks() if task not in before and not task.done()]


@pytest.mark.asyncio
async def test_empty_source_produces_no_event():
    async def source():
        if False:
            yield "unused"

    assert [chunk async for chunk in stream_with_heartbeat(source())] == []

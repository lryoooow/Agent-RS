from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken

import app.agent.engine.orchestrator as orchestrator
from app.agent.engine.input import TurnInput
from app.agent.engine.router import RouteResult
from app.agent.engine.tools import RemoteSensingTool
from app.agent.tool_registry import get_tool
from app.agent.types import ToolRunResult


@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["main", "graph"])
async def test_close_stops_at_boundary_instead_of_consuming_next_steps(monkeypatch, strategy):
    calls = []
    closed = []
    captured = {}

    class Team:
        async def run_stream(self, **kwargs):
            captured.update(kwargs)
            try:
                calls.append("first")
                yield TextMessage(content="first", source="agent")
                calls.extend(["new-model-call", "second-tool"])
                yield TextMessage(content="second", source="agent")
            finally:
                closed.append(True)

    client = SimpleNamespace(close=AsyncMock())
    stop = SimpleNamespace(set=lambda: calls.append("stop")) if strategy == "graph" else None

    async def build(**kwargs):
        return orchestrator.Orchestration(
            team=Team(), stop=stop, model_client=client,
            route=RouteResult(strategy=strategy, flow_name=None, reason="test"),
        )

    monkeypatch.setattr(orchestrator, "build_orchestration", build)
    stream = orchestrator.stream_turn(TurnInput("test", ()), user_id=None)
    await anext(stream)  # metadata
    await anext(stream)  # first message
    await stream.aclose()
    await asyncio.sleep(0)
    assert "new-model-call" not in calls
    assert "second-tool" not in calls
    assert captured["cancellation_token"].is_cancelled()
    assert closed == [True]
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_at_metadata_also_closes_model_client(monkeypatch):
    client = SimpleNamespace(close=AsyncMock())

    async def build(**kwargs):
        return orchestrator.Orchestration(
            team=object(), stop=None, model_client=client,
            route=RouteResult(strategy="main", flow_name=None, reason="test"),
        )

    monkeypatch.setattr(orchestrator, "build_orchestration", build)
    stream = orchestrator.stream_turn(TurnInput("test", ()), user_id=None)
    await anext(stream)
    await stream.aclose()
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_token_never_prepares_or_runs_tool(monkeypatch):
    token = CancellationToken()
    token.cancel()
    prepare = AsyncMock()
    monkeypatch.setattr("app.agent.engine.tools.prepare_tool_call", prepare)
    monkeypatch.setattr("app.agent.engine.tools.run_prepared_tool", AsyncMock(return_value=ToolRunResult(tool_context="unexpected")))
    registered = get_tool("raster_inspect")
    args = registered.argument_model(imagery_id="94e758f38ede")
    with pytest.raises(asyncio.CancelledError):
        await RemoteSensingTool(registered).run(args, token)
    prepare.assert_not_awaited()


@pytest.mark.asyncio
async def test_tool_token_cancels_owned_execution_and_releases_it(monkeypatch):
    entered = asyncio.Event()
    exited = asyncio.Event()

    async def run(_):
        try:
            entered.set()
            await asyncio.Event().wait()
        finally:
            exited.set()

    monkeypatch.setattr("app.agent.engine.tools.prepare_tool_call", AsyncMock(return_value=object()))
    monkeypatch.setattr("app.agent.engine.tools.run_prepared_tool", run)
    token = CancellationToken()
    registered = get_tool("raster_inspect")
    args = registered.argument_model(imagery_id="94e758f38ede")
    task = asyncio.create_task(RemoteSensingTool(registered).run(args, token))
    await asyncio.wait_for(entered.wait(), 1)
    token.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert exited.is_set()


@pytest.mark.asyncio
async def test_completed_tool_token_does_not_cancel_callers_later_work(monkeypatch):
    monkeypatch.setattr("app.agent.engine.tools.prepare_tool_call", AsyncMock(return_value=object()))
    monkeypatch.setattr("app.agent.engine.tools.run_prepared_tool", AsyncMock(return_value=ToolRunResult(tool_context="ok")))
    token = CancellationToken()
    registered = get_tool("raster_inspect")
    args = registered.argument_model(imagery_id="94e758f38ede")
    assert await RemoteSensingTool(registered).run(args, token) == "ok"
    token.cancel()
    await asyncio.sleep(0)

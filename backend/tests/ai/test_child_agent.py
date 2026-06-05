from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, Field

from app.agent.child import ToolChildAgent
from app.agent.tool_registry import RegisteredTool
from app.agent.types import AgentTrace, RuntimeToolCall, ToolRunResult
from app.agent.tools.ndvi.schema import NDVIArguments, NDVI_TOOL
from app.core.settings import get_settings


class FakeArgs(BaseModel):
    query: str = Field(min_length=1)


async def _ok_runner(args: FakeArgs) -> ToolRunResult:
    return ToolRunResult(tool_context=f"ok:{args.query}", result_count=1, query=args.query)


async def _fallback_runner(_args: FakeArgs) -> ToolRunResult:
    return ToolRunResult(
        tool_context="fallback",
        metadata={"fallback_used": True, "execution_mode": "local_fallback"},
    )


async def _raising_runner(_args: FakeArgs) -> ToolRunResult:
    raise RuntimeError("boom")


def _tool(runner) -> RegisteredTool:
    return RegisteredTool(
        name="fake_tool",
        definition={"type": "function", "function": {"name": "fake_tool"}},
        argument_model=FakeArgs,
        runner=runner,
    )


@pytest.mark.asyncio
async def test_child_agent_rejects_unknown_tool() -> None:
    trace = AgentTrace(enabled=True)

    result = await ToolChildAgent(parent_run_id="parent").run(
        RuntimeToolCall(name="missing", arguments={}),
        user_id="user",
        trace=trace,
    )

    assert result.error == "tool_unavailable"
    assert trace.events[-1].metadata["child_run_id"]


@pytest.mark.asyncio
async def test_child_agent_rejects_invalid_args(monkeypatch) -> None:
    monkeypatch.setattr("app.agent.child.get_tool", lambda _name: _tool(_ok_runner))
    trace = AgentTrace(enabled=True)

    result = await ToolChildAgent(parent_run_id="parent").run(
        RuntimeToolCall(name="fake_tool", arguments={"query": ""}),
        user_id="user",
        trace=trace,
    )

    assert result.error
    assert result.metadata["error_code"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_child_agent_runs_valid_tool(monkeypatch) -> None:
    monkeypatch.setattr("app.agent.child.get_tool", lambda _name: _tool(_ok_runner))
    trace = AgentTrace(enabled=True)

    result = await ToolChildAgent(parent_run_id="parent").run(
        RuntimeToolCall(name="fake_tool", arguments={"query": "hello"}),
        user_id="user",
        trace=trace,
    )

    assert result.error is None
    assert result.tool_context == "ok:hello"
    assert [event.stage for event in trace.events] == [
        "tool_requested",
        "child_agent_running",
        "tool_execution_started",
        "tool_execution_completed",
        "tool_context_ready",
    ]
    assert trace.events[1].metadata["execution_kind"] == "tool"


@pytest.mark.asyncio
async def test_child_agent_catches_runner_exception(monkeypatch) -> None:
    monkeypatch.setattr("app.agent.child.get_tool", lambda _name: _tool(_raising_runner))
    trace = AgentTrace(enabled=True)

    result = await ToolChildAgent(parent_run_id="parent").run(
        RuntimeToolCall(name="fake_tool", arguments={"query": "hello"}),
        user_id="user",
        trace=trace,
    )

    assert result.error == "boom"
    assert any(event.stage == "tool_execution_failed" for event in trace.events)


@pytest.mark.asyncio
async def test_child_agent_emits_fallback_event(monkeypatch) -> None:
    monkeypatch.setattr("app.agent.child.get_tool", lambda _name: _tool(_fallback_runner))
    trace = AgentTrace(enabled=True)

    await ToolChildAgent(parent_run_id="parent").run(
        RuntimeToolCall(name="fake_tool", arguments={"query": "hello"}),
        user_id="user",
        trace=trace,
    )

    assert any(event.stage == "tool_fallback_used" for event in trace.events)


@pytest.mark.asyncio
async def test_child_agent_rejects_ndvi_for_non_owner(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    imagery_dir = tmp_path / imagery_id
    imagery_dir.mkdir(parents=True)
    (imagery_dir / "metadata.json").write_text(
        '{"filename":"sample.tif","owner_user_id":"other-user"}',
        encoding="utf-8",
    )
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    async def fail_runner(_args):
        raise AssertionError("runner should not execute for non-owner")

    monkeypatch.setattr(
        "app.agent.child.get_tool",
        lambda _name: RegisteredTool(
            name="calculate_ndvi",
            definition=NDVI_TOOL,
            argument_model=NDVIArguments,
            runner=fail_runner,
        ),
    )
    trace = AgentTrace(enabled=True)

    result = await ToolChildAgent(parent_run_id="parent").run(
        RuntimeToolCall(name="calculate_ndvi", arguments={"imagery_id": imagery_id}),
        user_id=get_settings().default_user_id,
        trace=trace,
    )

    assert result.error == "imagery_not_found_or_forbidden"

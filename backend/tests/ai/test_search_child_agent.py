from __future__ import annotations

import pytest

from app.agent.search_agent import SearchChildAgent
from app.agent.types import AgentTrace, RuntimeAgentCall, ToolRunResult
from app.core.settings import get_settings


def reset_settings() -> None:
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_search_child_agent_rejects_unknown_agent_name(monkeypatch) -> None:
    async def fail_runner(_args):
        raise AssertionError("search runner should not execute for unknown agent")

    monkeypatch.setattr("app.agent.search_agent.run_web_search", fail_runner)
    trace = AgentTrace(enabled=True)

    result = await SearchChildAgent(parent_run_id="parent").run(
        RuntimeAgentCall(
            name="not_web_search",
            arguments={"query": "latest ai news", "reason": "fresh info"},
        ),
        trace=trace,
    )

    assert result.error == "agent_unavailable"
    assert result.metadata["error_code"] == "agent_unavailable"
    assert trace.events[-1].metadata["execution_kind"] == "agent"


@pytest.mark.asyncio
async def test_search_child_agent_rejects_invalid_arguments() -> None:
    trace = AgentTrace(enabled=True)

    result = await SearchChildAgent(parent_run_id="parent").run(
        RuntimeAgentCall(name="web_search", arguments={"query": "", "reason": "fresh"}),
        trace=trace,
    )

    assert result.error
    assert result.metadata["error_code"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_search_child_agent_rejects_too_long_query(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_WEB_SEARCH_INPUT_MAX_CHARS", "8")
    reset_settings()
    trace = AgentTrace(enabled=True)

    result = await SearchChildAgent(parent_run_id="parent").run(
        RuntimeAgentCall(
            name="web_search",
            arguments={"query": "this query is too long", "reason": "fresh"},
        ),
        trace=trace,
    )

    assert result.error == "query 超过长度限制"
    assert result.metadata["error_code"] == "query_too_long"


@pytest.mark.asyncio
async def test_search_child_agent_runs_search_and_emits_agent_metadata(monkeypatch) -> None:
    reset_settings()

    async def ok_runner(args):
        return ToolRunResult(
            tool_context=f"search context:{args.query}",
            result_count=1,
            query=args.query,
        )

    monkeypatch.setattr("app.agent.search_agent.run_web_search", ok_runner)
    trace = AgentTrace(enabled=True)

    result = await SearchChildAgent(parent_run_id="parent").run(
        RuntimeAgentCall(
            name="web_search",
            arguments={"query": "latest ai news", "reason": "fresh"},
        ),
        trace=trace,
    )

    assert result.error is None
    assert result.tool_context == "search context:latest ai news"
    assert [event.stage for event in trace.events] == [
        "tool_requested",
        "child_agent_running",
        "tool_execution_started",
        "tool_execution_completed",
        "tool_context_ready",
    ]
    assert all(event.metadata.get("execution_kind") == "agent" for event in trace.events)
    assert all(event.metadata.get("dispatch_kind") == "agent" for event in trace.events)


@pytest.mark.asyncio
async def test_search_child_agent_catches_runner_exception(monkeypatch) -> None:
    reset_settings()

    async def raising_runner(_args):
        raise RuntimeError("boom")

    monkeypatch.setattr("app.agent.search_agent.run_web_search", raising_runner)
    trace = AgentTrace(enabled=True)

    result = await SearchChildAgent(parent_run_id="parent").run(
        RuntimeAgentCall(
            name="web_search",
            arguments={"query": "latest ai news", "reason": "fresh"},
        ),
        trace=trace,
    )

    assert result.error == "boom"
    assert any(event.stage == "tool_execution_failed" for event in trace.events)

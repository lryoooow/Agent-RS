from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.config import resolve_ai_config
from app.agent.routing import build_agent_route
from app.agent.search.cache import get_decision_cache, get_planner_decision_cache
from app.agent.tool_selector import TaskSelector
from app.agent.types import AgentTrace
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


class FakeCompletions:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)


async def _add_event(trace, _on_event, stage, label, **metadata):
    return trace.add(stage, label, **metadata)


def reset_state() -> None:
    get_settings.cache_clear()
    get_decision_cache().clear()
    get_planner_decision_cache().clear()


def _request(query: str) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": query}])


def _owned_imagery(root: Path, imagery_id: str, owner_user_id: str) -> None:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    (imagery_dir / "metadata.json").write_text(
        json.dumps({"filename": "sample.tif", "owner_user_id": owner_user_id}),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_llm_mode_routes_non_keyword_question_to_full_pipeline(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_PLANNER_MODE", "llm")
    reset_state()

    route = build_agent_route("这件事是否需要外部核实", _request("这件事是否需要外部核实"))

    assert route.mode == "full_pipeline"
    assert route.candidate_agents == ("web_search",)
    assert "calculate_ndvi" in route.candidate_tools


@pytest.mark.asyncio
async def test_llm_mode_keeps_code_request_direct(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_PLANNER_MODE", "llm")
    reset_state()

    route = build_agent_route("帮我写一个排序函数", _request("帮我写一个排序函数"))

    assert route.mode == "direct_chat"
    assert route.skip_retrieval is True


@pytest.mark.asyncio
async def test_llm_mode_keeps_plain_ndvi_explanation_direct(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_PLANNER_MODE", "llm")
    reset_state()

    route = build_agent_route("什么是 NDVI？", _request("什么是 NDVI？"))

    assert route.mode == "direct_chat"
    assert route.reason == "ndvi_explanation_no_tool"
    assert route.skip_retrieval is True


@pytest.mark.asyncio
async def test_llm_selector_uses_planner_for_fresh_ndvi_explanation(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_PLANNER_MODE", "llm")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "介绍一下 NDVI 的最新进展 2025"
    request = _request(query)
    route = build_agent_route(query, request)
    completions = FakeCompletions(
        json.dumps(
            {
                "action": "call",
                "capability": "web_search",
                "arguments": {"query": query, "reason": "需要最新进展"},
                "reason": "fresh_ndvi",
            },
            ensure_ascii=False,
        )
    )
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert route.mode == "full_pipeline"
    assert selection.agent_call is not None
    assert selection.agent_call.name == "web_search"
    assert [event.stage for event in trace.events] == [
        "planner_started",
        "planner_completed",
        "planner_selected",
    ]


@pytest.mark.asyncio
async def test_llm_selector_uses_planner_for_web_search(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_PLANNER_MODE", "llm")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "这件事是否需要外部核实"
    request = _request(query)
    route = build_agent_route(query, request)
    completions = FakeCompletions(
        '{"action":"call","capability":"web_search","arguments":{"query":"这件事是否需要外部核实","reason":"需要外部验证"},"reason":"external_check"}'
    )
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert selection.agent_call is not None
    assert selection.agent_call.name == "web_search"
    assert [event.stage for event in trace.events] == [
        "planner_started",
        "planner_completed",
        "planner_selected",
    ]


@pytest.mark.asyncio
async def test_llm_selector_rejects_invalid_plan(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_PLANNER_MODE", "llm")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "这件事是否需要外部核实"
    request = _request(query)
    route = build_agent_route(query, request)
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(FakeCompletions('{"action":"call","capability":"missing","arguments":{},"reason":"bad"}')),
        config=resolve_ai_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert selection.agent_call is None
    assert selection.tool_call is None
    assert trace.events[-1].stage == "plan_validation_failed"


@pytest.mark.asyncio
async def test_llm_selector_uses_validated_cache(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_PLANNER_MODE", "llm")
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "这件事是否需要外部核实"
    request = _request(query)
    route = build_agent_route(query, request)
    first = FakeCompletions(
        '{"action":"call","capability":"web_search","arguments":{"query":"这件事是否需要外部核实","reason":"需要外部验证"},"reason":"external_check"}'
    )

    first_selection = await TaskSelector().select(
        client=FakeClient(first),
        config=resolve_ai_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
        route=route,
    )
    assert first_selection.agent_call is not None

    second = FakeCompletions('{"action":"none","capability":null,"arguments":{},"reason":"wrong"}')
    trace = AgentTrace(enabled=True)
    second_selection = await TaskSelector().select(
        client=FakeClient(second),
        config=resolve_ai_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert second_selection.agent_call is not None
    assert second.calls == []
    assert trace.events[-1].metadata["cached"] is True


@pytest.mark.asyncio
async def test_llm_selector_emits_guard_stage_for_forbidden_imagery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AGENT_PLANNER_MODE", "llm")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    _owned_imagery(tmp_path, "94e758f38ede", "other-user")
    query = "计算这张影像的 NDVI"
    request = _request(query)
    route = build_agent_route(query, request)
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(
            FakeCompletions(
                '{"action":"call","capability":"calculate_ndvi","arguments":{"imagery_id":"94e758f38ede"},"reason":"ndvi"}'
            )
        ),
        config=resolve_ai_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert selection.tool_call is None
    assert trace.events[-1].stage == "capability_guard_rejected"
    assert trace.events[-1].metadata["error"] == "imagery_not_found_or_forbidden"

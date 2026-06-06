from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.config import resolve_ai_config
from app.agent.search.cache import CachedDecision, get_decision_cache
from app.agent.search_planner import SearchPlanner
from app.agent.types import AgentTrace
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


class FakeCompletions:
    def __init__(self, *responses: str, fail_first: bool = False, fail_all: bool = False):
        self.responses = list(responses)
        self.calls = []
        self.fail_first = fail_first
        self.fail_all = fail_all

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_all or (self.fail_first and len(self.calls) == 1):
            raise RuntimeError("planner failed")
        content = self.responses.pop(0) if self.responses else "NO"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)


async def _add_event(trace, _on_event, stage, label, **metadata):
    return trace.add(stage, label, **metadata)


def reset_state() -> None:
    get_settings.cache_clear()
    get_decision_cache().clear()


def _request(query: str) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": query}])


@pytest.mark.asyncio
async def test_planner_yes_returns_search_and_writes_cache(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "Transformer 注意力机制的实际应用边界"
    request = _request(query)
    completions = FakeCompletions("YES")

    call = await SearchPlanner().plan(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        web_search_available=True,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )

    assert call is not None
    assert call.name == "web_search"
    assert completions.calls[0]["extra_body"] == {"enable_thinking": False}
    scope = "|".join(
        [
            get_settings().default_user_id,
            request.conversation_id or "no-conversation",
            resolve_ai_config().model,
            "web:on",
            f"rag:{int(request.use_rag)}",
            f"memory:{int(request.use_memory)}",
        ]
    )
    assert get_decision_cache().get_decision(query, scope=scope) == CachedDecision.SEARCH


@pytest.mark.asyncio
async def test_planner_no_returns_none_and_writes_cache(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "Transformer 注意力机制的实际应用边界"
    request = _request(query)
    trace = AgentTrace(enabled=True)

    call = await SearchPlanner().plan(
        client=FakeClient(FakeCompletions("NO")),
        config=resolve_ai_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        web_search_available=True,
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert call is None
    assert trace.events[-1].stage == "direct_answer"


@pytest.mark.asyncio
async def test_planner_fallback_to_main_model(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    completions = FakeCompletions("YES", fail_first=True)
    trace = AgentTrace(enabled=True)

    call = await SearchPlanner().plan(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=_request("Transformer 注意力机制的实际应用边界"),
        query="Transformer 注意力机制的实际应用边界",
        user_id=get_settings().default_user_id,
        web_search_available=True,
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert call is not None
    assert len(completions.calls) == 2
    assert [event.stage for event in trace.events][:2] == ["planning", "planning_fallback"]


@pytest.mark.asyncio
async def test_planner_failure_degrades_to_no_tool(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    trace = AgentTrace(enabled=True)

    call = await SearchPlanner().plan(
        client=FakeClient(FakeCompletions(fail_all=True)),
        config=resolve_ai_config(),
        request=_request("Transformer 注意力机制的实际应用边界"),
        query="Transformer 注意力机制的实际应用边界",
        user_id=get_settings().default_user_id,
        web_search_available=True,
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert call is None
    assert trace.events[-1].stage == "tool_unavailable"


@pytest.mark.asyncio
async def test_planner_skips_when_search_unavailable() -> None:
    reset_state()
    trace = AgentTrace(enabled=True)
    completions = FakeCompletions("YES")

    call = await SearchPlanner().plan(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=_request("Transformer 注意力机制的实际应用边界"),
        query="Transformer 注意力机制的实际应用边界",
        user_id=get_settings().default_user_id,
        web_search_available=False,
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert call is None
    assert completions.calls == []
    assert trace.events[-1].stage == "tool_unavailable"

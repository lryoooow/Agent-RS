from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.config import ResolvedAIConfig
from app.agent.routing import ALL_CANDIDATE_TOOLS, build_agent_route
from app.agent.search.cache import get_planner_decision_cache
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
    get_planner_decision_cache().clear()


def _config() -> ResolvedAIConfig:
    return ResolvedAIConfig(
        provider="openai-compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=60,
        max_retries=0,
        trust_env_proxy=False,
    )


def _request(query: str) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": query}])


def _owned_imagery(root: Path, imagery_id: str, owner_user_id: str) -> None:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    (imagery_dir / "metadata.json").write_text(
        json.dumps({"filename": "sample.tif", "owner_user_id": owner_user_id}),
        encoding="utf-8",
    )


def test_non_empty_question_routes_to_llm_pipeline_by_default() -> None:
    reset_state()

    route = build_agent_route("帮我写一个排序函数", _request("帮我写一个排序函数"))

    assert route.mode == "full_pipeline"
    assert route.reason == "llm_planner_route"
    assert route.candidate_agents == ("web_search",)
    assert route.candidate_tools == ALL_CANDIDATE_TOOLS


@pytest.mark.asyncio
async def test_selector_returns_none_when_planner_says_no_call(monkeypatch) -> None:
    reset_state()
    query = "帮我写一个排序函数"
    request = _request(query)
    route = build_agent_route(query, request)
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(FakeCompletions('{"action":"none","capability":null,"arguments":{},"reason":"direct"}')),
        config=_config(),
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
    assert [event.stage for event in trace.events] == [
        "planner_started",
        "planner_completed",
        "planner_no_call",
    ]


@pytest.mark.asyncio
async def test_selector_uses_planner_for_web_search(monkeypatch) -> None:
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
        config=_config(),
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
@pytest.mark.parametrize(
    ("index_type", "query"),
    [
        ("ndwi", "计算影像的 NDWI"),
        ("mndwi", "计算影像的 MNDWI"),
        ("savi", "计算影像的 SAVI"),
        ("msavi", "计算影像的 MSAVI"),
        ("gndvi", "计算影像的 GNDVI"),
        ("ndmi", "计算影像的 NDMI"),
        ("nbr", "计算影像的 NBR"),
        ("bsi", "计算影像的 BSI"),
    ],
)
async def test_selector_accepts_all_spectral_index_plans(monkeypatch, tmp_path: Path, index_type: str, query: str) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)
    request = _request(query)
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(
            FakeCompletions(
                json.dumps(
                    {
                        "action": "call",
                        "capability": "calculate_spectral_index",
                        "arguments": {"imagery_id": "94e758f38ede", "index_type": index_type},
                        "reason": "spectral_index",
                    }
                )
            )
        ),
        config=_config(),
        request=request,
        query=query,
        user_id=user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=build_agent_route(query, request),
    )

    assert selection.tool_call is not None
    assert selection.tool_call.name == "calculate_spectral_index"
    assert selection.tool_call.arguments["index_type"] == index_type


@pytest.mark.asyncio
async def test_selector_rejects_invalid_plan_without_caching(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "这件事是否需要外部核实"
    request = _request(query)
    route = build_agent_route(query, request)
    trace = AgentTrace(enabled=True)
    first = FakeCompletions('{"action":"call","capability":"missing","arguments":{},"reason":"bad"}')

    selection = await TaskSelector().select(
        client=FakeClient(first),
        config=_config(),
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
    assert selection.planner_error_context
    assert trace.events[-1].stage == "plan_validation_failed"

    second = FakeCompletions(
        '{"action":"call","capability":"web_search","arguments":{"query":"ok","reason":"retry"},"reason":"external_check"}'
    )
    second_selection = await TaskSelector().select(
        client=FakeClient(second),
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
        route=route,
    )
    assert second_selection.agent_call is not None
    assert second.calls


@pytest.mark.asyncio
async def test_selector_uses_validated_cache(monkeypatch) -> None:
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
        config=_config(),
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
        config=_config(),
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
async def test_selector_emits_guard_stage_for_forbidden_imagery(monkeypatch, tmp_path: Path) -> None:
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
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert selection.tool_call is None
    assert selection.planner_error_context
    assert trace.events[-1].stage == "capability_guard_rejected"
    assert trace.events[-1].metadata["error"] == "imagery_not_found_or_forbidden"

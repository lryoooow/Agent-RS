from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.config import resolve_ai_config
from app.agent.routing import AgentRoute
from app.agent.tool_selector import TaskSelector
from app.agent.search.cache import get_decision_cache
from app.agent.types import AgentTrace
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


class FakeCompletions:
    def __init__(self, *responses, fail_first: bool = False):
        self.responses = list(responses)
        self.calls = []
        self.fail_first = fail_first

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail_first and len(self.calls) == 1:
            raise RuntimeError("planning failed")
        content = self.responses.pop(0) if self.responses else "NO"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self, completions):
        self.chat = SimpleNamespace(completions=completions)


async def _add_event(trace, _on_event, stage, label, **metadata):
    return trace.add(stage, label, **metadata)


def reset_settings() -> None:
    get_settings.cache_clear()
    get_decision_cache().clear()


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
async def test_selector_selects_ndvi_for_owned_imagery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_settings()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)
    request = ChatRequest(
        messages=[
            {"role": "system", "content": "当前上传影像：ID=94e758f38ede"},
            {"role": "user", "content": "请计算 NDVI"},
        ]
    )

    selection = await TaskSelector().select(
        client=FakeClient(FakeCompletions("NO")),
        config=resolve_ai_config(),
        request=request,
        query="请计算 NDVI",
        user_id=user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )

    assert selection.tool_call is not None
    assert selection.tool_call.name == "calculate_ndvi"


@pytest.mark.asyncio
async def test_selector_skip_does_not_call_planner(monkeypatch) -> None:
    reset_settings()
    completions = FakeCompletions("YES")

    selection = await TaskSelector().select(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=_request("你好"),
        query="你好",
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )

    assert selection.tool_call is None
    assert completions.calls == []


@pytest.mark.asyncio
async def test_selector_force_search_without_planner(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    completions = FakeCompletions("NO")

    selection = await TaskSelector().select(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=_request("今天有什么遥感新闻"),
        query="今天有什么遥感新闻",
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )

    assert selection.agent_call is not None
    assert selection.agent_call.name == "web_search"
    assert completions.calls == []


@pytest.mark.asyncio
async def test_selector_planner_yes_writes_cache(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    query = "Transformer 注意力机制怎么工作"

    selection = await TaskSelector().select(
        client=FakeClient(FakeCompletions("YES")),
        config=resolve_ai_config(),
        request=_request(query),
        query=query,
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )

    assert selection.agent_call is not None
    cached = await TaskSelector().select(
        client=FakeClient(FakeCompletions("NO")),
        config=resolve_ai_config(),
        request=_request(query),
        query=query,
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )
    assert cached.agent_call is not None
    assert cached.reason == "planner"


@pytest.mark.asyncio
async def test_selector_planning_fallback_to_main_model(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    completions = FakeCompletions("YES", fail_first=True)

    selection = await TaskSelector().select(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=_request("Transformer 注意力机制怎么工作"),
        query="Transformer 注意力机制怎么工作",
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )

    assert selection.agent_call is not None
    assert len(completions.calls) == 2


@pytest.mark.asyncio
async def test_selector_does_not_select_search_when_route_disallows_agent(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    completions = FakeCompletions("YES")
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=_request("今天有什么遥感新闻"),
        query="今天有什么遥感新闻",
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_tools=("calculate_ndvi",)),
    )

    assert selection.agent_call is None
    assert selection.reason == "search_not_allowed_by_route"
    assert completions.calls == []


@pytest.mark.asyncio
async def test_selector_does_not_select_ndvi_when_route_disallows_tool(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_settings()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)
    request = ChatRequest(
        messages=[
            {"role": "system", "content": "当前上传影像：ID=94e758f38ede"},
            {"role": "user", "content": "请计算 NDVI"},
        ]
    )

    selection = await TaskSelector().select(
        client=FakeClient(FakeCompletions("NO")),
        config=resolve_ai_config(),
        request=request,
        query="请计算 NDVI",
        user_id=user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_agents=("web_search",)),
    )

    assert selection.tool_call is None
    assert selection.reason == "ndvi_not_allowed_by_route"


@pytest.mark.asyncio
async def test_selector_search_unavailable_does_not_call_planner(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "")
    reset_settings()
    completions = FakeCompletions("YES")

    selection = await TaskSelector().select(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=_request("Transformer 注意力机制怎么工作"),
        query="Transformer 注意力机制怎么工作",
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_agents=("web_search",)),
    )

    assert selection.agent_call is None
    assert selection.reason == "planner_no_tool"
    assert completions.calls == []

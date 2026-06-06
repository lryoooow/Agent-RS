from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.config import resolve_ai_config
from app.agent.llm_planner import LLMCapabilityPlanner, capability_snapshot
from app.agent.types import AgentTrace
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


class FakeCompletions:
    def __init__(self, content: str | None = None, *, fail: bool = False):
        self.content = content or '{"action":"none","capability":null,"arguments":{},"reason":"direct"}'
        self.fail = fail
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("planner failed")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)


async def _add_event(trace, _on_event, stage, label, **metadata):
    return trace.add(stage, label, **metadata)


def reset_settings() -> None:
    get_settings.cache_clear()


def _owned_imagery(root: Path, imagery_id: str, owner_user_id: str) -> None:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    (imagery_dir / "metadata.json").write_text(
        json.dumps(
            {
                "filename": "sample.tif",
                "owner_user_id": owner_user_id,
                "band_count": 4,
                "width": 16,
                "height": 16,
                "crs": "EPSG:4326",
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_llm_planner_parses_json_decision(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    completions = FakeCompletions(
        '{"action":"call","capability":"web_search","arguments":{"query":"明天杭州天气","reason":"天气"},"reason":"needs_weather"}'
    )
    trace = AgentTrace(enabled=True)

    decision = await LLMCapabilityPlanner().plan(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "明天杭州天气"}]),
        query="明天杭州天气",
        capabilities=capability_snapshot(),
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert decision.action == "call"
    assert decision.capability == "web_search"
    assert decision.arguments == {"query": "明天杭州天气", "reason": "天气"}
    assert completions.calls[0]["extra_body"] == {"enable_thinking": False}
    assert "tools" not in completions.calls[0]


@pytest.mark.asyncio
async def test_llm_planner_invalid_json_degrades(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    trace = AgentTrace(enabled=True)

    decision = await LLMCapabilityPlanner().plan(
        client=FakeClient(FakeCompletions("我认为不需要工具")),
        config=resolve_ai_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "你好"}]),
        query="你好",
        capabilities=capability_snapshot(),
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert decision.action == "none"
    assert decision.reason == "invalid_json"
    assert trace.events[-1].stage == "planner_invalid"


@pytest.mark.asyncio
async def test_llm_planner_provider_failure_degrades(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    trace = AgentTrace(enabled=True)

    decision = await LLMCapabilityPlanner().plan(
        client=FakeClient(FakeCompletions(fail=True)),
        config=resolve_ai_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "明天杭州天气"}]),
        query="明天杭州天气",
        capabilities=capability_snapshot(),
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert decision.action == "none"
    assert decision.reason == "planner_error"
    assert trace.events[-1].stage == "planner_invalid"


@pytest.mark.asyncio
async def test_llm_planner_injects_current_user_imagery_inventory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_settings()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)
    _owned_imagery(tmp_path, "aaaaaaaaaaaa", "other-user")
    completions = FakeCompletions()
    trace = AgentTrace(enabled=True)

    await LLMCapabilityPlanner().plan(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "计算这张影像的 NDVI"}]),
        query="计算这张影像的 NDVI",
        user_id=user_id,
        capabilities=capability_snapshot(),
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    sent_messages = completions.calls[0]["messages"]
    inventory_blocks = [
        message["content"]
        for message in sent_messages
        if "Current user imagery inventory" in message["content"]
    ]
    assert inventory_blocks
    assert "94e758f38ede" in inventory_blocks[0]
    assert "aaaaaaaaaaaa" not in inventory_blocks[0]


@pytest.mark.asyncio
async def test_llm_planner_injects_inventory_without_imagery_keyword_in_llm_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("AGENT_PLANNER_MODE", "llm")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_settings()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)
    completions = FakeCompletions()
    trace = AgentTrace(enabled=True)

    await LLMCapabilityPlanner().plan(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "处理一下我刚传的那个文件"}]),
        query="处理一下我刚传的那个文件",
        user_id=user_id,
        capabilities=capability_snapshot(),
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    sent_messages = completions.calls[0]["messages"]
    inventory_blocks = [
        message["content"]
        for message in sent_messages
        if "Current user imagery inventory" in message["content"]
    ]
    assert inventory_blocks
    assert "94e758f38ede" in inventory_blocks[0]

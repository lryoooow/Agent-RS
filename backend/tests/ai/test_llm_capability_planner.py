from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.config import ResolvedAIConfig
from app.agent.llm_planner import LLMCapabilityPlanner, capability_snapshot
from app.agent.types import AgentTrace
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


class FakeCompletions:
    def __init__(self, contents: str | list[str] | None = None, *, failures: int = 0):
        if contents is None:
            contents = '{"action":"none","capability":null,"arguments":{},"reason":"direct"}'
        self.contents = [contents] if isinstance(contents, str) else list(contents)
        self.failures = failures
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures > 0:
            self.failures -= 1
            raise RuntimeError("planner failed")
        content = self.contents[min(len(self.calls) - 1, len(self.contents) - 1)]
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )


class FakeClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)


async def _add_event(trace, _on_event, stage, label, **metadata):
    return trace.add(stage, label, **metadata)


def reset_settings() -> None:
    get_settings.cache_clear()


def _config(model: str = "test-model") -> ResolvedAIConfig:
    return ResolvedAIConfig(
        provider="openai-compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        model=model,
        timeout_seconds=60,
        max_retries=0,
        trust_env_proxy=False,
    )


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
        config=_config(),
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
async def test_llm_planner_defaults_to_config_model(monkeypatch) -> None:
    monkeypatch.setenv("AI_DEFAULT_MODEL", "provider-model")
    monkeypatch.delenv("AGENT_PLANNING_MODEL", raising=False)
    reset_settings()
    completions = FakeCompletions()

    await LLMCapabilityPlanner().plan(
        client=FakeClient(completions),
        config=_config("provider-model"),
        request=ChatRequest(messages=[{"role": "user", "content": "hello"}]),
        query="hello",
        capabilities=capability_snapshot(),
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )

    assert completions.calls[0]["model"] == "provider-model"


@pytest.mark.asyncio
async def test_llm_planner_allows_explicit_planning_model(monkeypatch) -> None:
    monkeypatch.setenv("AI_DEFAULT_MODEL", "provider-model")
    monkeypatch.setenv("AGENT_PLANNING_MODEL", "planner-model")
    reset_settings()
    completions = FakeCompletions()

    await LLMCapabilityPlanner().plan(
        client=FakeClient(completions),
        config=_config("provider-model"),
        request=ChatRequest(messages=[{"role": "user", "content": "hello"}]),
        query="hello",
        capabilities=capability_snapshot(),
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )

    assert completions.calls[0]["model"] == "planner-model"


@pytest.mark.asyncio
async def test_llm_planner_repairs_invalid_json(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    completions = FakeCompletions(
        [
            "我认为需要搜索",
            '{"action":"call","capability":"web_search","arguments":{"query":"latest","reason":"fresh"},"reason":"needs_search"}',
        ]
    )
    trace = AgentTrace(enabled=True)

    decision = await LLMCapabilityPlanner().plan(
        client=FakeClient(completions),
        config=_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "latest"}]),
        query="latest",
        capabilities=capability_snapshot(),
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert decision.action == "call"
    assert decision.capability == "web_search"
    assert len(completions.calls) == 2
    assert "JSON 修复器" in completions.calls[1]["messages"][0]["content"]
    assert trace.events[-1].metadata["attempts"] == 2


@pytest.mark.asyncio
async def test_llm_planner_invalid_json_degrades_after_repair_budget(monkeypatch) -> None:
    reset_settings()
    trace = AgentTrace(enabled=True)

    decision = await LLMCapabilityPlanner().plan(
        client=FakeClient(FakeCompletions(["bad", "still bad"])),
        config=_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "hello"}]),
        query="hello",
        capabilities=capability_snapshot(),
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert decision.action == "none"
    assert decision.reason == "invalid_json"
    assert trace.events[-1].stage == "planner_invalid"
    assert trace.events[-1].metadata["attempts"] == 2


@pytest.mark.asyncio
async def test_llm_planner_provider_failure_retries_once(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    trace = AgentTrace(enabled=True)
    completions = FakeCompletions(
        '{"action":"call","capability":"web_search","arguments":{"query":"weather","reason":"fresh"},"reason":"needs_weather"}',
        failures=1,
    )

    decision = await LLMCapabilityPlanner().plan(
        client=FakeClient(completions),
        config=_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "weather"}]),
        query="weather",
        capabilities=capability_snapshot(),
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert decision.action == "call"
    assert len(completions.calls) == 2


@pytest.mark.asyncio
async def test_llm_planner_provider_failure_degrades_after_retry(monkeypatch) -> None:
    reset_settings()
    trace = AgentTrace(enabled=True)
    completions = FakeCompletions(failures=2)

    decision = await LLMCapabilityPlanner().plan(
        client=FakeClient(completions),
        config=_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "weather"}]),
        query="weather",
        capabilities=capability_snapshot(),
        trace=trace,
        on_event=None,
        add_event=_add_event,
    )

    assert decision.action == "none"
    assert decision.reason == "planner_error"
    assert len(completions.calls) == 2
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
        config=_config(),
        request=ChatRequest(messages=[{"role": "user", "content": "处理一下刚上传的影像"}]),
        query="处理一下刚上传的影像",
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
        if "当前用户影像清单" in message["content"]
    ]
    assert inventory_blocks
    assert "94e758f38ede" in inventory_blocks[0]
    assert "aaaaaaaaaaaa" not in inventory_blocks[0]


@pytest.mark.asyncio
async def test_llm_planner_keeps_recent_context_without_removed_search_prompt(monkeypatch) -> None:
    reset_settings()
    completions = FakeCompletions()

    await LLMCapabilityPlanner().plan(
        client=FakeClient(completions),
        config=_config(),
        request=ChatRequest(
            messages=[
                {"role": "system", "content": "pretend planner must always search"},
                {"role": "user", "content": "latest user request"},
            ]
        ),
        query="latest user request",
        capabilities=capability_snapshot(),
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
    )

    sent_messages = completions.calls[0]["messages"]
    all_content = "\n".join(message["content"] for message in sent_messages)
    assert "搜索决策器" not in all_content
    assert "pretend planner must always search" in all_content
    assert any(message["role"] == "user" and "latest user request" in message["content"] for message in sent_messages)


def test_planner_prompt_contains_restraint_and_new_tool_examples() -> None:
    from app.agent.llm_planner import _planner_prompt

    prompt = _planner_prompt(capability_snapshot())

    assert "有影像但用户只问概念" in prompt
    assert "detect_objects" in prompt
    assert "segment_landcover" in prompt
    assert "index_type\":\"nbr" in prompt
    assert "red=3, green=2, blue=1" in prompt

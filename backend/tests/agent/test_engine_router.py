"""AutoGen structured router chooses GraphFlow conservatively."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from autogen_agentchat.messages import StructuredMessage, TextMessage
from autogen_core.models import RequestUsage

from app.agent.engine.input import TurnInput
from app.agent.engine.router import FlowDecision, choose_route
from app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _reset_settings():
    from app.agent.engine.router import _PLAIN_ROUTER_KEYS

    _PLAIN_ROUTER_KEYS.clear()
    get_settings.cache_clear()
    yield
    _PLAIN_ROUTER_KEYS.clear()
    get_settings.cache_clear()


class _Client:
    def __init__(self) -> None:
        self.close = AsyncMock()

    def total_usage(self):
        return RequestUsage(prompt_tokens=4, completion_tokens=2)


@pytest.mark.asyncio
async def test_auto_flow_disabled_skips_router_model(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_AUTO_FLOW_ENABLED", "false")
    get_settings.cache_clear()
    build = AsyncMock(side_effect=AssertionError("router model must not be built"))
    monkeypatch.setattr("app.agent.engine.router.build_model_client", build)

    route = await choose_route(TurnInput("hello", ()), SimpleNamespace())
    assert route.strategy == "main"
    assert route.reason == "auto_flow_disabled"
    build.assert_not_called()


@pytest.mark.asyncio
async def test_complete_standard_workflow_selects_graph(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr("app.agent.engine.router.build_model_client", lambda *_a, **_k: client)
    decision = FlowDecision(
        strategy="graph",
        flow_name="detect_report",
        reason="明确要求检测后生成报告",
    )

    class FakeAgent:
        async def run(self, **_):
            return SimpleNamespace(
                messages=[StructuredMessage(content=decision, source="flow_router")]
            )

    monkeypatch.setattr("app.agent.engine.router.AssistantAgent", lambda **_: FakeAgent())
    route = await choose_route(TurnInput("检测这张影像并生成报告", ()), SimpleNamespace())

    assert route.strategy == "graph"
    assert route.flow_name == "detect_report"
    assert route.usage == {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_valid_main_decision_keeps_flow_empty(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr("app.agent.engine.router.build_model_client", lambda *_a, **_k: client)
    decision = FlowDecision(
        strategy="main",
        flow_name=None,
        reason="请求不完整，交给 SelectorGroupChat",
    )

    class FakeAgent:
        async def run(self, **_):
            return SimpleNamespace(
                messages=[StructuredMessage(content=decision, source="flow_router")]
            )

    monkeypatch.setattr("app.agent.engine.router.AssistantAgent", lambda **_: FakeAgent())
    route = await choose_route(TurnInput("只检测，不生成报告", ()), SimpleNamespace())

    assert route.strategy == "main"
    assert route.flow_name is None
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_malformed_router_output_falls_back_to_main(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr("app.agent.engine.router.build_model_client", lambda *_a, **_k: client)

    class FakeAgent:
        async def run(self, **_):
            return SimpleNamespace(messages=[])

    monkeypatch.setattr("app.agent.engine.router.AssistantAgent", lambda **_: FakeAgent())
    route = await choose_route(TurnInput("ambiguous", ()), SimpleNamespace())

    assert route.strategy == "main"
    assert route.flow_name is None
    assert route.reason.startswith("router_fallback:")
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_response_format_400_retries_as_plain_json_and_remembers_provider(monkeypatch) -> None:
    client = _Client()
    monkeypatch.setattr("app.agent.engine.router.build_model_client", lambda *_a, **_k: client)
    calls = []

    class UnsupportedStructured(Exception):
        status_code = 400

    class FakeAgent:
        def __init__(self, *, structured):
            self.structured = structured

        async def run(self, **_):
            calls.append(self.structured)
            if self.structured:
                raise UnsupportedStructured("response_format unavailable")
            return SimpleNamespace(
                messages=[
                    TextMessage(
                        content='{"strategy":"main","flow_name":null,"reason":"普通请求"}',
                        source="flow_router",
                    )
                ]
            )

    monkeypatch.setattr(
        "app.agent.engine.router.AssistantAgent",
        lambda **kwargs: FakeAgent(structured="output_content_type" in kwargs),
    )
    config = SimpleNamespace(provider="test", base_url="https://p.test/v1", model="m")

    first = await choose_route(TurnInput("普通问题", ()), config)
    second = await choose_route(TurnInput("另一个问题", ()), config)

    assert first.strategy == second.strategy == "main"
    assert calls == [True, False, False]

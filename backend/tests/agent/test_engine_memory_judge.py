"""AutoGen structured memory-decision adapter."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from autogen_agentchat.messages import StructuredMessage

from app.agent.engine.memory_judge import MemoryDecision, decide_memory


@pytest.mark.asyncio
async def test_decide_memory_returns_structured_output_and_closes_client(monkeypatch) -> None:
    client = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        "app.agent.engine.memory_judge.build_model_client", lambda *_a, **_k: client
    )
    decision = MemoryDecision(
        remember=True,
        content="用户偏好中文",
        memory_type="preference",
        importance=0.8,
    )

    class FakeAgent:
        async def run(self, **_):
            return SimpleNamespace(
                messages=[StructuredMessage(content=decision, source="memory_judge")]
            )

    monkeypatch.setattr(
        "app.agent.engine.memory_judge.AssistantAgent", lambda **_: FakeAgent()
    )
    result = await decide_memory(
        config=SimpleNamespace(),
        model_override="judge-model",
        system_message="judge",
        task="dialogue",
    )
    assert result == decision
    client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_decide_memory_closes_client_when_agent_fails(monkeypatch) -> None:
    client = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        "app.agent.engine.memory_judge.build_model_client", lambda *_a, **_k: client
    )

    class FakeAgent:
        async def run(self, **_):
            raise RuntimeError("provider failed")

    monkeypatch.setattr(
        "app.agent.engine.memory_judge.AssistantAgent", lambda **_: FakeAgent()
    )
    with pytest.raises(RuntimeError, match="provider failed"):
        await decide_memory(
            config=SimpleNamespace(),
            model_override=None,
            system_message="judge",
            task="dialogue",
        )
    client.close.assert_awaited_once()

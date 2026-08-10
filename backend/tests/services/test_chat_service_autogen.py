"""_chat_via_autogen / _stream_via_autogen 集成胶水层测试。

这两个方法是 AGENT_ENGINE=autogen 时生产环境实际跑的代码路径，
负责把 engine 层的 AutogenTurnOutput 翻译成与 legacy 同构的
ChatResponse 和 SSE 事件序列。此前它们零测试覆盖。

这里 mock 掉 engine.service.complete_turn 和 stream_turn_events
（它们的内部逻辑由 test_engine_stream_contract.py 等覆盖），
只验这层胶水的翻译正确性：字段映射、事件时序、异常收尾。
"""
from __future__ import annotations

import json
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from app.agent.engine.service import AutogenTurnOutput
from app.agent.types import AgentEvent, AgentTrace
from app.schemas.chat import ChatRequest, ProviderConfig
from app.services.chat_service import ChatService
from app.core.settings import get_settings


@pytest.fixture(autouse=True)
def autogen_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    monkeypatch.setenv("AGENT_ENGINE", "autogen")
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _request() -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": "什么是 NDVI？"}],
        provider_config=ProviderConfig(
            base_url="https://client.example/v1",
            api_key="client-key",
            model="client-model",
        ),
    )


def _turn_output(*, content: str = "NDVI 是归一化植被指数。", **kw) -> AutogenTurnOutput:
    return AutogenTurnOutput(
        content=content,
        trace=AgentTrace(enabled=True),
        retrieved_chunks=0,
        rag_trace={"use_rag": False, "use_memory": True},
        **kw,
    )


# ================================================================ 非流式


@pytest.mark.asyncio
async def test_chat_via_autogen_produces_legacy_isomorphic_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_chat_via_autogen 产出的 ChatResponse 字段应与 legacy 同构。"""
    fake_turn = _turn_output()
    monkeypatch.setattr(
        "app.agent.engine.service.complete_turn",
        AsyncMock(return_value=fake_turn),
    )
    monkeypatch.setattr("app.agent.ai_service.save_assistant_response", AsyncMock(return_value="msg-id"))
    monkeypatch.setattr("app.agent.ai_service.schedule_after_response", lambda *a, **kw: None)

    # mock 掉持久化准备，返回固定上下文
    from app.agent.persistence import PersistenceContext
    monkeypatch.setattr(
        "app.agent.ai_service.prepare_persistence",
        AsyncMock(return_value=PersistenceContext(
            user_id="u1",
            conversation_id="c1",
            user_message_id="um1",
            assistant_message_id="am1",
            user_content="什么是 NDVI？",
        )),
    )

    response = await ChatService().chat(_request())

    assert response.content == "NDVI 是归一化植被指数。"
    assert response.model == "client-model"
    assert response.finish_reason == "stop"
    assert response.retrieved_chunks == 0
    assert response.rag_trace == {"use_rag": False, "use_memory": True}
    assert response.conversation_id == "c1"


@pytest.mark.asyncio
async def test_chat_via_autogen_marks_failed_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engine 抛异常时 mark_assistant_failed 被调用。"""
    monkeypatch.setattr(
        "app.agent.engine.service.complete_turn",
        AsyncMock(side_effect=RuntimeError("engine exploded")),
    )
    marked: list = []
    monkeypatch.setattr(
        "app.agent.ai_service.mark_assistant_failed",
        AsyncMock(side_effect=lambda persistence, exc: marked.append((persistence, exc))),
    )
    from app.agent.persistence import PersistenceContext
    monkeypatch.setattr(
        "app.agent.ai_service.prepare_persistence",
        AsyncMock(return_value=PersistenceContext(
            user_id="u1", conversation_id="c1", user_message_id="um1",
            assistant_message_id="am1", user_content="hi",
        )),
    )

    with pytest.raises(Exception):
        await ChatService().chat(_request())

    # mark_assistant_failed 由外层 chat() 统一调用，恰好一次
    assert len(marked) == 1
    assert isinstance(marked[0][1], RuntimeError)


# ================================================================ 流式


def _data(event: str) -> dict:
    return json.loads(event.split("data: ", 1)[1].rstrip())


@pytest.mark.asyncio
async def test_stream_via_autogen_event_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """事件序列：meta → analyzing → agent_status* → preparing → answering → delta* → done。"""
    from app.agent.types import AgentEvent

    async def fake_stream(*, query, user_id, use_rag, use_memory, config=None):
        yield "status", AgentEvent(stage="context_assembled", label="上下文已装配")
        yield "delta", "NDVI 是"
        yield "delta", "归一化植被指数。"
        yield "final", _turn_output()

    monkeypatch.setattr("app.agent.engine.service.stream_turn_events", fake_stream)
    monkeypatch.setattr("app.agent.ai_service.save_streamed_assistant", AsyncMock())
    monkeypatch.setattr("app.agent.ai_service.schedule_after_response", lambda *a, **kw: None)
    from app.agent.persistence import PersistenceContext
    monkeypatch.setattr(
        "app.agent.ai_service.prepare_persistence",
        AsyncMock(return_value=PersistenceContext(
            user_id="u1", conversation_id="c1", user_message_id="um1",
            assistant_message_id="am1", user_content="hi",
        )),
    )

    events = [e async for e in ChatService().stream_chat(_request())]

    # meta
    assert events[0].startswith("event: meta\n")
    assert _data(events[0])["model"] == "client-model"

    # analyzing
    assert _data(events[1])["status"] == "analyzing"

    # agent_status (context_assembled)
    assert events[2].startswith("event: agent_status\n")
    assert '"context_assembled"' in events[2]

    # preparing + answering（第一个 delta 前补发）
    statuses = [_data(e)["status"] for e in events if e.startswith("event: analysis_status\n")]
    assert "preparing" in statuses
    assert "answering" in statuses
    assert statuses.index("preparing") < statuses.index("answering")

    # deltas
    deltas = [e for e in events if e.startswith("event: delta\n")]
    assert len(deltas) == 2
    assert _data(deltas[0])["content"] == "NDVI 是"
    assert _data(deltas[1])["content"] == "归一化植被指数。"

    # done
    done_events = [e for e in events if e.startswith("event: done\n")]
    assert len(done_events) == 1
    done = _data(done_events[0])
    assert done["finish_reason"] == "stop"
    assert done["rag_trace"] == {"use_rag": False, "use_memory": True}


@pytest.mark.asyncio
async def test_stream_via_autogen_no_delta_supplements_preparing_answering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 delta 分片时（如整段来自工具摘要）也能补发 preparing/answering + 正文。"""
    from app.agent.types import AgentEvent

    async def fake_stream(*, query, user_id, use_rag, use_memory, config=None):
        yield "status", AgentEvent(stage="context_assembled", label="上下文已装配")
        # 没有 delta，直接 final（turn.content 有值）
        yield "final", _turn_output(content="整段来自工具摘要。")

    monkeypatch.setattr("app.agent.engine.service.stream_turn_events", fake_stream)
    monkeypatch.setattr("app.agent.ai_service.save_streamed_assistant", AsyncMock())
    monkeypatch.setattr("app.agent.ai_service.schedule_after_response", lambda *a, **kw: None)
    from app.agent.persistence import PersistenceContext
    monkeypatch.setattr(
        "app.agent.ai_service.prepare_persistence",
        AsyncMock(return_value=PersistenceContext(
            user_id="u1", conversation_id="c1", user_message_id="um1",
            assistant_message_id="am1", user_content="hi",
        )),
    )

    events = [e async for e in ChatService().stream_chat(_request())]

    statuses = [_data(e)["status"] for e in events if e.startswith("event: analysis_status\n")]
    assert "preparing" in statuses
    assert "answering" in statuses

    deltas = [e for e in events if e.startswith("event: delta\n")]
    assert len(deltas) >= 1
    full = "".join(_data(e)["content"] for e in deltas)
    assert "整段来自工具摘要" in full


@pytest.mark.asyncio
async def test_stream_via_autogen_error_emits_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engine 抛异常时发 error 事件并标记失败。"""
    async def fake_stream(*, query, user_id, use_rag, use_memory, config=None):
        yield "status", AgentEvent(stage="context_assembled", label="上下文已装配")
        raise RuntimeError("stream broke")
        yield  # unreachable  # pragma: no cover

    monkeypatch.setattr("app.agent.engine.service.stream_turn_events", fake_stream)
    marked: list = []
    monkeypatch.setattr(
        "app.agent.ai_service.mark_assistant_failed",
        AsyncMock(side_effect=lambda persistence, exc: marked.append(exc)),
    )
    from app.agent.persistence import PersistenceContext
    monkeypatch.setattr(
        "app.agent.ai_service.prepare_persistence",
        AsyncMock(return_value=PersistenceContext(
            user_id="u1", conversation_id="c1", user_message_id="um1",
            assistant_message_id="am1", user_content="hi",
        )),
    )

    events = [e async for e in ChatService().stream_chat(_request())]

    error_events = [e for e in events if e.startswith("event: error\n")]
    assert len(error_events) == 1
    assert len(marked) == 1
    assert isinstance(marked[0], RuntimeError)

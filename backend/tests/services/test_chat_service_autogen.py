"""AutoGen AIService 的 HTTP 响应与 SSE 胶水层测试。

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
    monkeypatch.setenv("AI_API_KEY", "test-key")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    # P0-1：这些用例的 provider 用不可解析假域名 client.example，加入白名单跳过 SSRF 的 DNS 校验。
    monkeypatch.setenv("AI_PROVIDER_ALLOWED_HOSTS", "client.example")
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
async def test_chat_produces_http_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AutoGen 回合产出标准 ChatResponse。"""
    fake_turn = _turn_output()
    monkeypatch.setattr(
        "app.agent.ai_service.complete_turn",
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
async def test_chat_marks_failed_on_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """engine 抛异常时 mark_assistant_failed 被调用。"""
    monkeypatch.setattr(
        "app.agent.ai_service.complete_turn",
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

    async def fake_stream(*, request, user_id, config=None):
        yield "status", AgentEvent(stage="context_assembled", label="上下文已装配")
        yield "delta", "NDVI 是"
        yield "delta", "归一化植被指数。"
        yield "final", _turn_output()

    monkeypatch.setattr("app.agent.ai_service.stream_turn_events", fake_stream)
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

    # 安全阶段摘要先于框架状态；摘要只来自固定枚举，不含模型推理文本。
    summaries = [e for e in events if e.startswith("event: thinking_summary\n")]
    assert _data(summaries[0]) == {
        "stage": "context",
        "label": "正在整理对话上下文与可用资料",
    }

    # agent_status (context_assembled)
    agent_events = [e for e in events if e.startswith("event: agent_status\n")]
    assert '"context_assembled"' in agent_events[0]

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
async def test_legacy_thinking_kind_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """即使旧 engine 在滚动升级期间仍产出 thinking，HTTP 层也不能再转发。"""
    raw_secret = "RAW_CHAIN_OF_THOUGHT_DO_NOT_EXPOSE"

    async def fake_stream(*, request, user_id, config=None):
        yield "thinking", raw_secret
        yield "delta", "公开答案"
        yield "final", _turn_output(content="公开答案")

    monkeypatch.setattr("app.agent.ai_service.stream_turn_events", fake_stream)
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

    assert raw_secret not in "".join(events)
    assert not [e for e in events if e.startswith("event: thinking\n")]


@pytest.mark.asyncio
async def test_stream_via_autogen_no_delta_supplements_preparing_answering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 delta 分片时（如整段来自工具摘要）也能补发 preparing/answering + 正文。"""
    from app.agent.types import AgentEvent

    async def fake_stream(*, request, user_id, config=None):
        yield "status", AgentEvent(stage="context_assembled", label="上下文已装配")
        # 没有 delta，直接 final（turn.content 有值）
        yield "final", _turn_output(content="整段来自工具摘要。")

    monkeypatch.setattr("app.agent.ai_service.stream_turn_events", fake_stream)
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
    async def fake_stream(*, request, user_id, config=None):
        yield "status", AgentEvent(stage="context_assembled", label="上下文已装配")
        raise RuntimeError("stream broke")
        yield  # unreachable  # pragma: no cover

    monkeypatch.setattr("app.agent.ai_service.stream_turn_events", fake_stream)
    marked: list = []
    monkeypatch.setattr(
        "app.agent.ai_service.mark_assistant_failed",
        AsyncMock(side_effect=lambda persistence, exc, **_: marked.append(exc)),
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


# ================================================================ P2-7：usage / finish_reason


@pytest.mark.asyncio
async def test_chat_via_autogen_persists_real_usage_and_maps_finish_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P2-7：autogen 非流式须落真实 token usage，并把 stop_reason 映射成 finish_reason。"""
    fake_turn = _turn_output(
        usage={"input_tokens": 120, "output_tokens": 80, "total_tokens": 200},
        stop_reason="Terminated: Maximum number of messages 12 reached.",
    )
    monkeypatch.setattr("app.agent.ai_service.complete_turn", AsyncMock(return_value=fake_turn))
    save = AsyncMock(return_value="msg-id")
    monkeypatch.setattr("app.agent.ai_service.save_assistant_response", save)
    monkeypatch.setattr("app.agent.ai_service.schedule_after_response", lambda *a, **kw: None)
    from app.agent.persistence import PersistenceContext
    monkeypatch.setattr(
        "app.agent.ai_service.prepare_persistence",
        AsyncMock(return_value=PersistenceContext(
            user_id="u1", conversation_id="c1", user_message_id="um1",
            assistant_message_id="am1", user_content="hi",
        )),
    )

    response = await ChatService().chat(_request())

    assert response.finish_reason == "length"  # 命中「maximum」→ length（不再写死 stop）
    assert save.call_args.kwargs["usage"] == {
        "input_tokens": 120, "output_tokens": 80, "total_tokens": 200
    }
    assert save.call_args.kwargs["finish_reason"] == "length"


@pytest.mark.asyncio
async def test_stream_via_autogen_emits_real_usage_in_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """P2-7 流式：done 事件带真实 usage；落库 done_payload 透传 usage。"""
    usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}

    async def fake_stream(*, request, user_id, config=None):
        yield "delta", "答复"
        yield "final", _turn_output(usage=usage)

    monkeypatch.setattr("app.agent.ai_service.stream_turn_events", fake_stream)
    save = AsyncMock()
    monkeypatch.setattr("app.agent.ai_service.save_streamed_assistant", save)
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
    done = _data([e for e in events if e.startswith("event: done\n")][0])
    assert done["usage"] == usage
    assert save.call_args.kwargs["done_payload"]["usage"] == usage

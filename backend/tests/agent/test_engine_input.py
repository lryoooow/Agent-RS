"""HTTP chat context is converted once into isolated AutoGen model contexts."""

from types import SimpleNamespace

import pytest
from autogen_core.models import AssistantMessage, SystemMessage, UserMessage

from app.agent.engine.input import build_turn_input
from app.schemas.chat import AnalysisROI, ChatMessage, ChatRequest


@pytest.mark.asyncio
async def test_turn_input_preserves_trusted_context_and_removes_duplicate_task(monkeypatch) -> None:
    async def fake_context(request, *, user_id, skip_retrieval):
        assert user_id == "u1"
        assert skip_retrieval is True
        return SimpleNamespace(
            messages=[
                {"role": "system", "content": "安全边界 + 地图 + 影像清单 + 历史结果"},
                {"role": "user", "content": "上一轮问题"},
                {"role": "assistant", "content": "上一轮回答"},
                {"role": "user", "content": "当前问题"},
            ]
        )

    monkeypatch.setattr("app.agent.engine.input.build_provider_request_context", fake_context)
    request = ChatRequest(messages=[ChatMessage(role="user", content="当前问题")])
    turn = await build_turn_input(request, user_id="u1")

    assert turn.query == "当前问题"
    assert [type(message) for message in turn.initial_messages] == [
        SystemMessage,
        UserMessage,
        AssistantMessage,
    ]
    assert [message.content for message in turn.initial_messages] == [
        "安全边界 + 地图 + 影像清单 + 历史结果",
        "上一轮问题",
        "上一轮回答",
    ]


@pytest.mark.asyncio
async def test_each_agent_gets_an_independent_context_clone(monkeypatch) -> None:
    async def fake_context(*_args, **_kwargs):
        return SimpleNamespace(messages=[{"role": "system", "content": "trusted"}])

    monkeypatch.setattr("app.agent.engine.input.build_provider_request_context", fake_context)
    turn = await build_turn_input(
        ChatRequest(messages=[ChatMessage(role="user", content="question")]),
        user_id=None,
    )
    first = turn.context()
    second = turn.context()
    await first.add_message(UserMessage(content="first only", source="user"))

    assert [message.content for message in await first.get_messages()] == ["trusted", "first only"]
    assert [message.content for message in await second.get_messages()] == ["trusted"]


@pytest.mark.asyncio
async def test_turn_input_converts_roi_to_trusted_segment_arguments(monkeypatch) -> None:
    async def fake_context(*_args, **_kwargs):
        return SimpleNamespace(messages=[])

    monkeypatch.setattr("app.agent.engine.input.build_provider_request_context", fake_context)
    request = ChatRequest(
        messages=[ChatMessage(role="user", content="分类框选区域")],
        analysis_roi=AnalysisROI(kind="geo", bbox=(110.0, 20.0, 111.0, 21.0)),
    )
    turn = await build_turn_input(request, user_id="u1")

    assert turn.trusted_tool_arguments == {
        "segment_landcover": {
            "bbox": [110.0, 20.0, 111.0, 21.0],
            "bbox_crs": "EPSG:4326",
            "pixel_bbox": None,
        }
    }

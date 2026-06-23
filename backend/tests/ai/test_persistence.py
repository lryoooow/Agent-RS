from types import SimpleNamespace

import pytest

from app.agent.persistence import PersistenceContext, _assistant_metadata, schedule_after_response


@pytest.mark.asyncio
async def test_schedule_after_response_keeps_embedding_ids_and_content_paired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = []
    embedded_targets = []

    def fake_create_task(coro):
        tasks.append(coro)
        return SimpleNamespace()

    async def fake_embed_messages(targets):
        embedded_targets.extend(targets)

    async def fake_maybe_store_memory(**_):
        return None

    monkeypatch.setattr("app.agent.persistence.asyncio.create_task", fake_create_task)
    monkeypatch.setattr("app.agent.persistence._embed_messages", fake_embed_messages)
    monkeypatch.setattr("app.agent.persistence.maybe_store_memory", fake_maybe_store_memory)

    schedule_after_response(
        PersistenceContext(
            user_id="00000000-0000-4000-8000-000000000001",
            conversation_id="00000000-0000-4000-8000-000000000301",
            user_message_id=None,
            assistant_message_id="00000000-0000-4000-8000-000000000303",
            user_content="user text",
        ),
        assistant_content="assistant text",
    )

    for task in tasks:
        await task

    assert embedded_targets == [
        ("00000000-0000-4000-8000-000000000303", "assistant text")
    ]


def test_assistant_metadata_embeds_structured_results() -> None:
    # A2 写入端：跑了工具的轮次，结构化结果与 finish_reason 一并落库（供跨轮回注/报告读取）。
    geo = {"type": "segmentation", "imagery_id": "d722c20e1234", "classes": []}
    tool = {"type": "raster_inspect", "imagery_id": "d722c20e1234", "band_count": 4}
    meta = _assistant_metadata(finish_reason="stop", geospatial_result=geo, tool_result=tool)
    assert meta == {"finish_reason": "stop", "geospatial_result": geo, "tool_result": tool}


def test_assistant_metadata_omits_absent_results() -> None:
    # 边界：纯对话轮（无工具结果）只存 finish_reason，不写空键，保持 metadata 精简。
    assert _assistant_metadata(finish_reason="stop", geospatial_result=None, tool_result=None) == {
        "finish_reason": "stop"
    }
    # 空 dict 也视作无结果，不写键（避免注入空块）。
    assert _assistant_metadata(finish_reason=None, geospatial_result={}, tool_result={}) == {
        "finish_reason": None
    }

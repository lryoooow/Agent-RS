from types import SimpleNamespace

import pytest

from app.lib.ai.persistence import PersistenceContext, schedule_after_response


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

    monkeypatch.setattr("app.lib.ai.persistence.asyncio.create_task", fake_create_task)
    monkeypatch.setattr("app.lib.ai.persistence._embed_messages", fake_embed_messages)
    monkeypatch.setattr("app.lib.ai.persistence.maybe_store_memory", fake_maybe_store_memory)

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

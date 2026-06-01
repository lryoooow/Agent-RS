import logging

import pytest

from app.lib.ai.memory_judge import maybe_store_memory
from app.shared.settings import get_settings


@pytest.mark.asyncio
async def test_memory_judge_non_json_response_logs_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class FakeMessage:
        content = "我无法返回 JSON"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    class FakeCompletions:
        async def create(self, **_):
            return FakeResponse()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    class FakeConfig:
        model = "cheap-model"

    async def fake_fetch_optional_pool():
        return object()

    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_MIN_USER_CHARS", "1")
    get_settings.cache_clear()
    monkeypatch.setattr("app.lib.ai.memory_judge.fetch_optional_pool", fake_fetch_optional_pool)
    monkeypatch.setattr("app.lib.ai.memory_judge.resolve_ai_config", lambda **_: FakeConfig())
    monkeypatch.setattr("app.lib.ai.memory_judge.create_chat_client", lambda _: FakeClient())

    try:
        with caplog.at_level(logging.WARNING):
            await maybe_store_memory(
                user_id="00000000-0000-4000-8000-000000000001",
                conversation_id="00000000-0000-4000-8000-000000000002",
                user_content="请记住我喜欢简洁回复",
                assistant_content="好的",
                source_message_id="00000000-0000-4000-8000-000000000003",
            )

        assert "Memory judge returned non-JSON payload" in caplog.text
        assert "Memory judge pipeline failed" not in caplog.text
    finally:
        get_settings.cache_clear()

import logging
from unittest.mock import AsyncMock

import pytest

from app.agent.memory_judge import (
    _normalize_importance,
    _normalize_memory_type,
    maybe_store_memory,
)
from app.agent.memory_types import DEFAULT_IMPORTANCE, DEFAULT_MEMORY_TYPE
from app.core.settings import get_settings


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
    monkeypatch.setattr("app.agent.memory_judge.fetch_optional_pool", fake_fetch_optional_pool)
    monkeypatch.setattr("app.agent.memory_judge.resolve_ai_config", lambda **_: FakeConfig())
    monkeypatch.setattr("app.agent.memory_judge.create_chat_client", lambda _: FakeClient())

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


# ================================================================ 归一化函数


@pytest.mark.parametrize("raw, expected", [
    (0.8, 0.8),           # 正常小数
    (1.0, 1.0),           # 上界
    (0.0, 0.0),           # 下界
    (85, 0.85),           # 百分制 → 缩放
    (100, 1.0),           # 百分制上界
    (150, 1.0),           # 超 100 → 夹紧
    (-0.5, 0.0),          # 负数 → 下界
    ("0.6", 0.6),         # 字符串数字
    ("abc", DEFAULT_IMPORTANCE),  # 非法字符串 → 默认
    (None, DEFAULT_IMPORTANCE),   # None → 默认
])
def test_normalize_importance(raw, expected) -> None:
    assert _normalize_importance(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("fact", "fact"),
    ("preference", "preference"),
    ("constraint", "constraint"),
    ("project", "project"),
    ("unknown_type", DEFAULT_MEMORY_TYPE),   # 未知 → 回退
    ("", DEFAULT_MEMORY_TYPE),
    (None, DEFAULT_MEMORY_TYPE),
])
def test_normalize_memory_type(raw, expected) -> None:
    assert _normalize_memory_type(raw) == expected


# ================================================================ 正路径：remember=true


@pytest.mark.asyncio
async def test_memory_judge_remember_true_calls_insert_with_normalized_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """remember=true 时 insert_memory 被调用且字段经过归一化。"""

    class FakeMessage:
        content = '{"remember": true, "content": "用户偏好中文回复", "memory_type": "preference", "importance": 80, "tags": ["lang"]}'

    class FakeResponse:
        choices = [type("C", (), {"message": FakeMessage()})()]

    class FakeClient:
        chat = type("Chat", (), {"completions": type("Comp", (), {
            "create": AsyncMock(return_value=FakeResponse())
        })()})()

    class FakeConfig:
        model = "judge-model"

    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_MIN_USER_CHARS", "1")
    get_settings.cache_clear()

    fake_pool = type("Pool", (), {"acquire": lambda self: _FakeConn()})()
    monkeypatch.setattr("app.agent.memory_judge.fetch_optional_pool", AsyncMock(return_value=fake_pool))
    monkeypatch.setattr("app.agent.memory_judge.resolve_ai_config", lambda **_: FakeConfig())
    monkeypatch.setattr("app.agent.memory_judge.create_chat_client", lambda _: FakeClient())
    monkeypatch.setattr("app.agent.memory_judge.get_embedding_service", lambda: type("E", (), {
        "embed_text": AsyncMock(return_value=[0.1] * 10)
    })())

    inserted: dict = {}
    async def fake_insert(conn, **kwargs):
        inserted.update(kwargs)
    monkeypatch.setattr("app.agent.memory_judge.insert_memory", fake_insert)

    try:
        await maybe_store_memory(
            user_id="u1", conversation_id="c1",
            user_content="以后都用中文回复我",
            assistant_content="好的",
            source_message_id="m1",
        )
    finally:
        get_settings.cache_clear()

    assert inserted["content"] == "用户偏好中文回复"
    assert inserted["memory_type"] == "preference"
    assert inserted["importance"] == 0.8  # 80 → 0.8（百分制缩放）
    assert inserted["user_id"] == "u1"


# ================================================================ 早退路径


@pytest.mark.asyncio
async def test_memory_judge_skips_when_storage_inactive(monkeypatch) -> None:
    """storage_active=false → 直接返回，不调任何下游。"""
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    monkeypatch.setenv("MEMORY_JUDGE_ENABLED", "true")
    get_settings.cache_clear()

    # 如果没早退，这些 mock 会被调用，测试会失败
    monkeypatch.setattr("app.agent.memory_judge.fetch_optional_pool",
                        AsyncMock(side_effect=AssertionError("不该走到这里")))
    try:
        await maybe_store_memory(
            user_id="u1", conversation_id="c1",
            user_content="test", assistant_content="test",
            source_message_id="m1",
        )
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_memory_judge_skips_when_content_too_short(monkeypatch) -> None:
    """用户内容过短 → 直接返回。"""
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_MIN_USER_CHARS", "50")
    get_settings.cache_clear()

    monkeypatch.setattr("app.agent.memory_judge.fetch_optional_pool",
                        AsyncMock(side_effect=AssertionError("不该走到这里")))
    try:
        await maybe_store_memory(
            user_id="u1", conversation_id="c1",
            user_content="hi", assistant_content="hello",
            source_message_id="m1",
        )
    finally:
        get_settings.cache_clear()


class _FakeConn:
    """pool.acquire() 返回的假连接。"""
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False

"""长期记忆判断必须通过 AutoGen structured output。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agent.memory_judge import (
    MemoryDecision,
    _normalize_importance,
    _normalize_memory_type,
    maybe_store_memory,
)
from app.agent.memory_types import DEFAULT_IMPORTANCE, DEFAULT_MEMORY_TYPE
from app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _settings() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.8, 0.8),
        (1.0, 1.0),
        (0.0, 0.0),
        (85, 0.85),
        (100, 1.0),
        (150, 1.0),
        (-0.5, 0.0),
        ("0.6", 0.6),
        ("abc", DEFAULT_IMPORTANCE),
        (None, DEFAULT_IMPORTANCE),
    ],
)
def test_normalize_importance(raw, expected) -> None:
    assert _normalize_importance(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("fact", "fact"),
        ("preference", "preference"),
        ("constraint", "constraint"),
        ("project", "project"),
        ("unknown_type", DEFAULT_MEMORY_TYPE),
        ("", DEFAULT_MEMORY_TYPE),
        (None, DEFAULT_MEMORY_TYPE),
    ],
)
def test_normalize_memory_type(raw, expected) -> None:
    assert _normalize_memory_type(raw) == expected


def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_MIN_USER_CHARS", "1")
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_structured_decision_is_stored_through_autogen_memory(monkeypatch) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(
        "app.agent.memory_judge.fetch_optional_pool", AsyncMock(return_value=object())
    )
    monkeypatch.setattr(
        "app.agent.memory_judge.resolve_ai_config", lambda **_: SimpleNamespace(model="judge")
    )

    decision = MemoryDecision(
        remember=True,
        content="用户偏好中文回复",
        memory_type="preference",
        importance=0.8,
        tags=["lang"],
    )

    decide = AsyncMock(return_value=decision)
    monkeypatch.setattr("app.agent.memory_judge.decide_memory", decide)
    added: list = []

    class FakeMemory:
        def __init__(self, *, user_id: str):
            assert user_id == "u1"

        async def add_text(self, content, *, metadata):
            added.append((content, metadata))

    monkeypatch.setattr("app.agent.memory_judge.PgVectorMemory", FakeMemory)

    await maybe_store_memory(
        user_id="u1",
        conversation_id="c1",
        user_content="以后都用中文回复我",
        assistant_content="好的",
        source_message_id="m1",
    )

    assert len(added) == 1
    assert added[0][0] == "用户偏好中文回复"
    assert added[0][1] == {
        "memory_type": "preference",
        "importance": 0.8,
        "tags": ["lang"],
        "source_session_id": "c1",
        "source_message_id": "m1",
    }
    decide.assert_awaited_once()


@pytest.mark.asyncio
async def test_missing_structured_decision_skips_storage_and_closes_client(
    monkeypatch, caplog
) -> None:
    _enable(monkeypatch)
    monkeypatch.setattr(
        "app.agent.memory_judge.fetch_optional_pool", AsyncMock(return_value=object())
    )
    monkeypatch.setattr("app.agent.memory_judge.decide_memory", AsyncMock(return_value=None))
    memory = AsyncMock()
    monkeypatch.setattr("app.agent.memory_judge.PgVectorMemory", memory)

    await maybe_store_memory(
        user_id="u1",
        conversation_id="c1",
        user_content="请记住我喜欢简洁回复",
        assistant_content="好的",
        source_message_id="m1",
    )

    assert "no structured decision" in caplog.text
    memory.assert_not_called()


@pytest.mark.asyncio
async def test_memory_judge_skips_when_storage_inactive(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    monkeypatch.setenv("MEMORY_JUDGE_ENABLED", "true")
    get_settings.cache_clear()
    pool = AsyncMock(side_effect=AssertionError("不应访问数据库"))
    monkeypatch.setattr("app.agent.memory_judge.fetch_optional_pool", pool)

    await maybe_store_memory(
        user_id="u1",
        conversation_id="c1",
        user_content="记住这个长期偏好",
        assistant_content="好",
        source_message_id="m1",
    )
    pool.assert_not_awaited()


@pytest.mark.asyncio
async def test_memory_judge_skips_short_content(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_ENABLED", "true")
    monkeypatch.setenv("MEMORY_JUDGE_MIN_USER_CHARS", "50")
    get_settings.cache_clear()
    pool = AsyncMock(side_effect=AssertionError("不应访问数据库"))
    monkeypatch.setattr("app.agent.memory_judge.fetch_optional_pool", pool)

    await maybe_store_memory(
        user_id="u1",
        conversation_id="c1",
        user_content="hi",
        assistant_content="hello",
        source_message_id="m1",
    )
    pool.assert_not_awaited()

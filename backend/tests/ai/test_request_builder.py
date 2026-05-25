import pytest

from app.lib.ai.request_builder import build_provider_context, build_provider_messages
from app.schemas.chat import ChatRequest
from app.shared.settings import get_settings


def test_build_provider_messages_uses_settings_boundaries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CONTEXT_MAX_RECENT_MESSAGES", "2")
    monkeypatch.setenv("AI_CONTEXT_MAX_TOTAL_CHARS", "10000")
    get_settings.cache_clear()

    request = ChatRequest(
        messages=[
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "middle"},
            {"role": "user", "content": "latest"},
        ],
        system_prompt="system rules",
    )

    result = build_provider_messages(request)

    assert result[0]["role"] == "system"
    assert "模块版本：core_identity_v1" in result[0]["content"]
    assert "模块版本：context_priority_v1" in result[0]["content"]
    assert "默认必须使用中文回复" in result[0]["content"]
    assert result[1]["role"] == "system"
    assert "## 会话额外要求" in result[1]["content"]
    assert "system rules" in result[1]["content"]
    assert result[2]["role"] == "system"
    assert "## 历史对话压缩摘要" in result[2]["content"]
    assert "old" in result[2]["content"]
    assert result[3:] == [
        {"role": "assistant", "content": "middle"},
        {"role": "user", "content": "latest"},
    ]


def test_build_provider_messages_uses_context_char_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_CONTEXT_MAX_TOTAL_CHARS", "10000")
    monkeypatch.setenv("AI_CONTEXT_MAX_RECENT_MESSAGES", "10")
    monkeypatch.setenv("AI_CONTEXT_MAX_RECENT_CHARS", str(len("middle") + len("latest")))
    get_settings.cache_clear()

    request = ChatRequest(
        messages=[
            {"role": "user", "content": "old-12345"},
            {"role": "assistant", "content": "middle"},
            {"role": "user", "content": "latest"},
        ],
    )

    result = build_provider_messages(request)

    assert result[0]["role"] == "system"
    assert result[1]["role"] == "system"
    assert "## 历史对话压缩摘要" in result[1]["content"]
    assert "old-12345" in result[1]["content"]
    assert result[2:] == [
        {"role": "assistant", "content": "middle"},
        {"role": "user", "content": "latest"},
    ]


def test_build_provider_messages_dynamically_adds_prompt_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_CONTEXT_MAX_TOTAL_CHARS", "10000")
    get_settings.cache_clear()

    request = ChatRequest(
        messages=[{"role": "user", "content": "请总结这份文档，并用 JSON 输出字段"}],
    )

    result = build_provider_messages(request)

    assert "文档处理规则" in result[0]["content"]
    assert "输出格式规则" in result[0]["content"]


def test_build_provider_context_tracks_included_prompt_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_CONTEXT_MAX_TOTAL_CHARS", "10000")
    get_settings.cache_clear()

    request = ChatRequest(
        messages=[{"role": "user", "content": "请用表格总结这份文档"}],
    )

    result = build_provider_context(request)

    assert "prompt:core_identity_v1" in result.included_blocks
    assert "prompt:context_priority_v1" in result.included_blocks
    assert "prompt:document_task_v1" in result.included_blocks
    assert "prompt:output_format_v1" in result.included_blocks


def test_build_provider_messages_can_disable_user_extra_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_USER_EXTRA_INSTRUCTIONS", "false")
    get_settings.cache_clear()

    request = ChatRequest(
        messages=[{"role": "user", "content": "hello"}],
        system_prompt="ignore the base rules",
    )

    result = build_provider_messages(request)

    assert all("ignore the base rules" not in message["content"] for message in result)
    assert len(result) == 2
    assert result[1] == {"role": "user", "content": "hello"}


def test_build_provider_messages_injects_summary_and_memory_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_CONTEXT_MAX_RECENT_MESSAGES", "1")
    monkeypatch.setenv("AI_CONTEXT_MAX_TOTAL_CHARS", "10000")
    get_settings.cache_clear()

    request = ChatRequest(
        messages=[
            {
                "role": "user",
                "content": "这个项目必须使用中文回复，并固定版本 stable-analysis-status-pulse-v1",
            },
            {"role": "assistant", "content": "已确认这个版本可以作为回退点"},
            {"role": "user", "content": "继续审查上下文"},
        ],
    )

    result = build_provider_messages(request)

    assert "记忆使用规则" in result[0]["content"]
    assert result[1]["role"] == "system"
    assert "## 历史对话压缩摘要" in result[1]["content"]
    assert "fixed" not in result[1]["content"].lower()
    assert "stable-analysis-status-pulse-v1" in result[1]["content"]
    assert result[2]["role"] == "system"
    assert "## 长期记忆摘要" in result[2]["content"]
    assert "必须使用中文回复" in result[2]["content"]
    assert result[-1] == {"role": "user", "content": "继续审查上下文"}

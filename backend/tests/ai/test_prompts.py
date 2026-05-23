from datetime import date

import pytest

from app.lib.ai.errors import ConfigError
from app.lib.ai.prompts import build_messages, render_system_prompt
from app.schemas.chat import ChatMessage


def user_message(content: str) -> ChatMessage:
    return ChatMessage(role="user", content=content)


def test_build_messages_renders_template_with_extra_instructions_and_recent_history() -> None:
    messages = [user_message(str(index)) for index in range(5)]

    result = build_messages(
        messages,
        "回答要更简洁。",
        max_history_messages=2,
        max_context_chars=100,
        current_date=date(2026, 5, 23),
    )

    assert result[0]["role"] == "system"
    assert "模板版本：system_chatbot_v1" in result[0]["content"]
    assert "当前日期：2026-05-23" in result[0]["content"]
    assert "默认必须使用中文回复" in result[0]["content"]
    assert "回答要更简洁。" in result[0]["content"]
    assert result[1:] == [{"role": "user", "content": "3"}, {"role": "user", "content": "4"}]


def test_build_messages_drops_old_messages_by_context_budget() -> None:
    messages = [
        user_message("old-12345"),
        user_message("middle"),
        user_message("latest"),
    ]

    result = build_messages(
        messages,
        max_history_messages=10,
        max_context_chars=len("middle") + len("latest"),
    )

    assert result[0]["role"] == "system"
    assert result[1:] == [
        {"role": "user", "content": "middle"},
        {"role": "user", "content": "latest"},
    ]


def test_build_messages_keeps_latest_message_when_single_message_exceeds_budget() -> None:
    messages = [
        user_message("old"),
        user_message("latest message is larger than the budget"),
    ]

    result = build_messages(messages, max_history_messages=10, max_context_chars=4)

    assert result[0]["role"] == "system"
    assert result[1:] == [
        {"role": "user", "content": "latest message is larger than the budget"},
    ]


def test_render_system_prompt_can_omit_user_extra_instructions() -> None:
    result = render_system_prompt(current_date=date(2026, 5, 23))

    assert "无额外要求。" in result
    assert "文档内容处理" in result
    assert "不能声称读取了用户没有提供的文件" in result


def test_render_system_prompt_rejects_missing_template() -> None:
    with pytest.raises(ConfigError, match="template not found"):
        render_system_prompt(template_name="missing_template")

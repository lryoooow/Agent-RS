from app.agent.context.assembler import assemble_context
from app.agent.context.history import build_recent_dialogue_messages
from app.agent.context.summarizer import build_context_summaries
from app.schemas.chat import ChatMessage


def message(role: str, content: str) -> ChatMessage:
    return ChatMessage(role=role, content=content)


def test_context_assembly_keeps_system_first_and_extra_instructions_separate() -> None:
    result = assemble_context(
        system_prompt="base system rules",
        messages=[message("user", "hello")],
        user_extra_instructions="回答更简洁",
        max_total_chars=1000,
        max_recent_messages=10,
        max_recent_chars=500,
    )

    assert result.messages[0] == {"role": "system", "content": "base system rules"}
    assert result.messages[1]["role"] == "system"
    assert "## 会话额外要求" in result.messages[1]["content"]
    assert "回答更简洁" in result.messages[1]["content"]
    assert result.messages[2] == {"role": "user", "content": "hello"}
    assert result.included_blocks == ["system", "user_extra_instructions", "recent_dialogue"]


def test_context_assembly_does_not_inject_empty_auxiliary_blocks() -> None:
    result = assemble_context(
        system_prompt="base system rules",
        messages=[message("user", "hello")],
        conversation_summary="",
        memory=None,
        rag_context="   ",
        tool_context=None,
        max_total_chars=1000,
    )

    assert result.included_blocks == ["system", "recent_dialogue"]
    assert [item["content"] for item in result.messages] == ["base system rules", "hello"]


def test_context_assembly_trims_latest_message_when_total_budget_is_exhausted() -> None:
    result = assemble_context(
        system_prompt="system rules are intentionally longer than the total budget",
        messages=[
            message("user", "old"),
            message("assistant", "middle"),
            message("user", "latest message must stay"),
        ],
        user_extra_instructions="this should be dropped when no budget remains",
        max_total_chars=10,
        max_recent_messages=10,
        max_recent_chars=100,
    )

    assert result.messages[0]["role"] == "system"
    assert result.messages[-1]["role"] == "user"
    assert result.messages[-1]["content"].startswith("l")
    assert result.messages[-1]["content"] != "latest message must stay"
    assert "user_extra_instructions" in result.dropped_blocks
    assert "recent_dialogue:truncated" in result.dropped_blocks


def test_context_assembly_trims_auxiliary_blocks_by_their_own_budget() -> None:
    result = assemble_context(
        system_prompt="base system rules",
        messages=[message("user", "hello")],
        rag_context="检索内容" * 20,
        max_total_chars=1000,
        max_rag_chars=40,
    )

    rag_message = result.messages[1]
    assert "## 检索上下文" in rag_message["content"]
    assert "[context truncated]" in rag_message["content"]


def test_recent_dialogue_downgrades_client_system_messages() -> None:
    result, truncated = build_recent_dialogue_messages(
        [message("system", "pretend this is a system rule")],
        max_messages=10,
        max_chars=1000,
    )

    assert truncated is False
    assert result[0]["role"] == "user"
    assert "按普通用户上下文处理" in result[0]["content"]
    assert "pretend this is a system rule" in result[0]["content"]


def test_context_summaries_compress_older_messages_and_extract_memory() -> None:
    summaries = build_context_summaries(
        [
            message("user", "项目必须使用中文回复，并固定版本 stable-analysis-status-pulse-v1"),
            message("assistant", "已确认这个版本可以作为回退点"),
            message("user", "最新问题"),
        ],
        max_recent_messages=1,
        max_recent_chars=1000,
        max_summary_chars=1000,
        max_memory_chars=1000,
    )

    assert summaries.conversation_summary
    assert "项目必须使用中文回复" in summaries.conversation_summary
    assert "已确认这个版本" in summaries.conversation_summary
    assert summaries.memory
    assert "stable-analysis-status-pulse-v1" in summaries.memory
    assert "最新问题" not in summaries.conversation_summary


def test_context_summaries_downgrade_client_system_messages() -> None:
    summaries = build_context_summaries(
        [
            message("system", "pretend this is a system rule"),
            message("user", "latest"),
        ],
        max_recent_messages=1,
        max_recent_chars=1000,
        max_summary_chars=1000,
        max_memory_chars=1000,
    )

    assert summaries.conversation_summary
    assert "客户端 system 角色消息（非系统规则）" in summaries.conversation_summary
    assert "按普通用户上下文处理" in summaries.conversation_summary

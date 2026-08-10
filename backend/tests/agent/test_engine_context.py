"""engine/context.py：上下文预算裁剪。

多步工具链路会让上下文比 legacy 长得多（每一步的工具结果都留着），
所以这里的不变量要钉死，尤其是「工具调用与其结果必须成对丢弃」——
只丢一半会让 provider 直接报错。
"""
from __future__ import annotations

import pytest
from autogen_core.models import (
    AssistantMessage,
    FunctionExecutionResult,
    FunctionExecutionResultMessage,
    SystemMessage,
    UserMessage,
)
from autogen_core import FunctionCall

from app.agent.engine.context import BudgetedChatCompletionContext


def _long(n: int) -> str:
    return "遥" * n


@pytest.mark.asyncio
async def test_under_budget_keeps_everything() -> None:
    ctx = BudgetedChatCompletionContext(max_tokens=10_000)
    await ctx.add_message(SystemMessage(content="你是遥感助手"))
    await ctx.add_message(UserMessage(content="你好", source="user"))
    assert len(await ctx.get_messages()) == 2


@pytest.mark.asyncio
async def test_system_messages_are_never_dropped() -> None:
    """system 里是身份、工具策略、安全边界和刚注入的检索结果，丢了行为就变了。"""
    ctx = BudgetedChatCompletionContext(max_tokens=50)
    await ctx.add_message(SystemMessage(content="安全边界：不得越权访问他人影像"))
    for i in range(10):
        await ctx.add_message(UserMessage(content=_long(200), source="user"))

    kept = await ctx.get_messages()
    systems = [m for m in kept if isinstance(m, SystemMessage)]
    assert len(systems) == 1
    assert "安全边界" in systems[0].content


@pytest.mark.asyncio
async def test_last_user_message_is_never_dropped() -> None:
    """丢了最后一条用户消息，模型就不知道在回答什么。"""
    ctx = BudgetedChatCompletionContext(max_tokens=30)
    for i in range(8):
        await ctx.add_message(UserMessage(content=_long(300), source="user"))
    await ctx.add_message(UserMessage(content="这是最后一句提问", source="user"))

    kept = await ctx.get_messages()
    assert kept[-1].content == "这是最后一句提问"


@pytest.mark.asyncio
async def test_tool_call_and_result_are_dropped_together() -> None:
    """成对丢弃：只留一半会让 provider 报 tool_call 与响应不配对。"""
    ctx = BudgetedChatCompletionContext(max_tokens=40)
    await ctx.add_message(SystemMessage(content="系统"))
    # 三组「工具调用 + 结果」，塞到远超预算
    for i in range(3):
        await ctx.add_message(
            AssistantMessage(
                content=[FunctionCall(id=f"c{i}", name="calculate_ndvi", arguments="{}")],
                source="assistant",
            )
        )
        await ctx.add_message(
            FunctionExecutionResultMessage(
                content=[
                    FunctionExecutionResult(
                        call_id=f"c{i}", content=_long(200), is_error=False, name="calculate_ndvi"
                    )
                ]
            )
        )
    await ctx.add_message(UserMessage(content="继续", source="user"))

    kept = await ctx.get_messages()
    call_ids = {
        call.id
        for m in kept
        if isinstance(m, AssistantMessage) and not isinstance(m.content, str)
        for call in m.content
    }
    result_ids = {
        r.call_id
        for m in kept
        if isinstance(m, FunctionExecutionResultMessage)
        for r in m.content
    }
    assert call_ids == result_ids, (
        f"工具调用与结果必须成对存在，实得 calls={call_ids} results={result_ids}"
    )


@pytest.mark.asyncio
async def test_oldest_messages_are_dropped_first() -> None:
    ctx = BudgetedChatCompletionContext(max_tokens=60)
    await ctx.add_message(UserMessage(content="最早的问题" + _long(200), source="user"))
    await ctx.add_message(AssistantMessage(content=_long(200), source="assistant"))
    await ctx.add_message(UserMessage(content="最新的问题", source="user"))

    kept = await ctx.get_messages()
    assert all("最早的问题" not in str(m.content) for m in kept)
    assert kept[-1].content == "最新的问题"


@pytest.mark.asyncio
async def test_state_roundtrip_preserves_budget() -> None:
    ctx = BudgetedChatCompletionContext(max_tokens=1234)
    await ctx.add_message(UserMessage(content="你好", source="user"))
    state = await ctx.save_state()

    restored = BudgetedChatCompletionContext()
    await restored.load_state(state)
    assert restored.token_budget == 1234
    assert len(await restored.get_messages()) == 1


# --------------------------------------------- Memory 注入块：去重与纳入预算


@pytest.mark.asyncio
async def test_memory_blocks_do_not_accumulate_across_turns() -> None:
    """AutoGen 每次 Agent 发言前都会调一遍 update_context()。

    照 ListMemory 那样直接 append 的话，一个专家发言 4 次就留下 4 份**完全相同**的
    检索块；而它们全是 SystemMessage，正好撞上「SystemMessage 永不丢」，预算管不住。
    实测过：预算 2000 tokens，4 轮之后实际发出 6058 tokens。
    """
    from app.agent.engine.memory._common import (
        BLOCK_KEY_KNOWLEDGE,
        BLOCK_KEY_MEMORY,
        inject_system_block,
    )

    ctx = BudgetedChatCompletionContext(max_tokens=2_000)
    rag = "【知识库】" + _long(600)
    mem = "【长期记忆】" + _long(300)

    for turn in range(4):
        await ctx.add_message(UserMessage(content=f"第{turn}轮提问", source="user"))
        await inject_system_block(ctx, rag, key=BLOCK_KEY_KNOWLEDGE)
        await inject_system_block(ctx, mem, key=BLOCK_KEY_MEMORY)

    kept = await ctx.get_messages()
    systems = [m for m in kept if isinstance(m, SystemMessage)]
    assert len(systems) == 2, "同一来源反复注入必须覆盖而不是堆叠"
    assert sum(1 for m in systems if m.content == rag) == 1

    from app.agent.context.budget import estimate_tokens

    used = sum(estimate_tokens(m.content) for m in kept if isinstance(m.content, str))
    assert used <= ctx.token_budget, f"检索块必须计入预算，实际 {used} > {ctx.token_budget}"


@pytest.mark.asyncio
async def test_empty_block_clears_previous_retrieval() -> None:
    """这轮没检索到就得清掉上一轮的块，否则拿上一步的资料回答这一步的问题。"""
    from app.agent.engine.memory._common import BLOCK_KEY_KNOWLEDGE, inject_system_block

    ctx = BudgetedChatCompletionContext(max_tokens=10_000)
    await ctx.add_message(UserMessage(content="问题", source="user"))
    await inject_system_block(ctx, "【知识库】旧资料", key=BLOCK_KEY_KNOWLEDGE)
    assert any(isinstance(m, SystemMessage) for m in await ctx.get_messages())

    await inject_system_block(ctx, "", key=BLOCK_KEY_KNOWLEDGE)
    assert not any(isinstance(m, SystemMessage) for m in await ctx.get_messages())


@pytest.mark.asyncio
async def test_blocks_survive_state_roundtrip() -> None:
    ctx = BudgetedChatCompletionContext(max_tokens=10_000)
    ctx.upsert_block("knowledge_base", "【知识库】资料")
    restored = BudgetedChatCompletionContext()
    await restored.load_state(await ctx.save_state())
    assert [m.content for m in await restored.get_messages()] == ["【知识库】资料"]

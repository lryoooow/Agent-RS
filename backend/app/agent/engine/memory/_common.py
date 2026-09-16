"""两个 Memory 实现共用的小工具。"""

from __future__ import annotations
import asyncio

import logging
from typing import Awaitable, Callable, TypeVar

from autogen_core.model_context import ChatCompletionContext
from autogen_core.models import SystemMessage, UserMessage

from app.agent.engine.turn_context import current_turn_state

logger = logging.getLogger(__name__)

# 注入块的来源标识。同一个 key 每轮覆盖上一轮，不同 key 各占一块。
BLOCK_KEY_KNOWLEDGE = "knowledge_base"
BLOCK_KEY_MEMORY = "user_memory"

_T = TypeVar("_T")


async def run_query_once_per_turn(
    source_key: str, query: str, run_query: Callable[[], Awaitable[_T]]
) -> _T:
    """同一回合内相同 (来源, 检索词) 只真正执行一次检索。

    AutoGen 在 Agent 每次模型调用前都调 memory.update_context()；多步工具循环里
    检索词（最新用户消息）不变，重复 embedding + 混合检索 + rerank 是纯浪费。
    回合作用域（turn_scope）之外的调用不缓存——单测直连等场景没有回合概念。

    并发下最多造成一次重复检索（check 与 set 之间有 await），不会出错；
    原生异步单线程里 dict 读写本身原子。
    """
    state = current_turn_state()
    if state is None:
        return await run_query()
    cache_key = f"{source_key}:{query}"
    cache = state.retrieval_cache
    if cache_key not in cache:
        # Publish the in-flight task before awaiting: parallel agents share one query.
        cache[cache_key] = asyncio.create_task(run_query())
    task = cache[cache_key]
    try:
        return await asyncio.shield(task)
    except Exception:
        if cache.get(cache_key) is task:
            cache.pop(cache_key, None)
        raise


async def latest_user_query(model_context: ChatCompletionContext) -> str:
    """取上下文里最后一条用户消息，作为检索 query。

    多步链路下上下文尾部往往是工具结果而不是用户消息，所以要往回找，
    而不是简单取最后一条。找不到就返回空串（调用方据此跳过检索）。
    """
    for message in reversed(await model_context.get_messages()):
        if isinstance(message, UserMessage):
            content = message.content
            if isinstance(content, str):
                return content.strip()
            # 多模态消息：只取文本片段
            parts = [p for p in content if isinstance(p, str)]
            if parts:
                return "\n".join(parts).strip()
    return ""


async def inject_system_block(
    model_context: ChatCompletionContext, block: str, *, key: str
) -> None:
    """把检索结果作为 SystemMessage 放进上下文。

    用 SystemMessage 而不是 UserMessage，是为了让模型能区分「检索到的资料」和
    「用户说的话」，不会把资料当成用户指令——这点与 AutoGen 内置的 `ListMemory` 一致。

    但**不能**照 `ListMemory` 那样直接 append：AutoGen 每次 Agent 发言前都会调一遍
    `update_context()`，append 会让同一份检索块在多步链路里堆叠好几份，还因为是
    SystemMessage 而躲过预算裁剪（实测 3 倍超支，详见 `engine/context.py` 模块文档）。

    所以优先走 `BudgetedChatCompletionContext.upsert_block()` 按 `key` 覆盖；
    上下文不是本项目那个实现时（外部调用方、单测）退回 append，保持能用。
    """
    upsert = getattr(model_context, "upsert_block", None)
    if callable(upsert):
        upsert(key, block)
        return
    # 退化路径只能追加，没有「撤回上一块」的语义，所以空块直接不写——
    # 否则清块会往上下文里塞一条空 SystemMessage。
    if block:
        await model_context.add_message(SystemMessage(content=block))

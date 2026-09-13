"""用户长期记忆接进 AutoGen Memory 协议。

读写 `public.memories`（pgvector）。与 RagMemory 不同，这个**是可写的**——
`memory_judge` 判断值得长期记住的内容经 `add()` 落库。

## 结构化字段

表里一直有 `memory_type` 与 `importance` 两列，但 `memory_judge` 从来只写
content + tags，两列永远是默认值 'fact' / 0.7（见迁移 0011 的说明）。
这里把它们纳入 `MemoryContent.metadata`，让记忆真正带上类型与重要度，
检索时可以据此排序与过滤。
"""

from __future__ import annotations

import logging
from typing import Any

from autogen_core import CancellationToken
from autogen_core.memory import (
    Memory,
    MemoryContent,
    MemoryMimeType,
    MemoryQueryResult,
    UpdateContextResult,
)
from autogen_core.model_context import ChatCompletionContext

from app.agent.embedding.service import get_embedding_service
from app.agent.engine.memory._common import (
    BLOCK_KEY_MEMORY,
    inject_system_block,
    latest_user_query,
    run_query_once_per_turn,
)
from app.agent.memory_types import DEFAULT_IMPORTANCE, DEFAULT_MEMORY_TYPE, MEMORY_TYPES
from app.agent.rag.formatter import format_retrieved_blocks
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool
from app.db.repositories.memory import insert_memory, list_relevant_memories

logger = logging.getLogger(__name__)



class PgVectorMemory(Memory):
    """用户长期记忆（pgvector 向量召回）。

    Args:
        user_id: 记忆归属用户。为 None 时全部方法 no-op——记忆必须有主，
            没有身份就既不该读别人的，也不该写成孤儿行。
        enabled: 对应请求里的 `use_memory`。
    """

    component_type = "memory"

    def __init__(self, *, user_id: str | None, enabled: bool = True) -> None:
        self._user_id = user_id
        self._enabled = enabled and bool(user_id)

    async def update_context(self, model_context: ChatCompletionContext) -> UpdateContextResult:
        query = await latest_user_query(model_context)
        if not query:
            return UpdateContextResult(memories=MemoryQueryResult(results=[]))

        # 回合级缓存：与 RagMemory 同理，工具循环里检索词不变，别重复检索。
        result = await run_query_once_per_turn(
            BLOCK_KEY_MEMORY, query, lambda: self.query(query)
        )
        if not result.results:
            # 与 RagMemory 同理：这轮没召回就清掉上一轮的块，别把旧记忆当新证据。
            await inject_system_block(model_context, "", key=BLOCK_KEY_MEMORY)
            return UpdateContextResult(memories=MemoryQueryResult(results=[]))

        block = format_retrieved_blocks(
            [
                {
                    "content": item.content,
                    **(item.metadata or {}),
                }
                for item in result.results
            ],
            title="memory",
        )
        await inject_system_block(model_context, block, key=BLOCK_KEY_MEMORY)
        return UpdateContextResult(memories=result)

    async def query(
        self,
        query: str | MemoryContent,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> MemoryQueryResult:
        if not self._enabled or not get_settings().storage_active:
            return MemoryQueryResult(results=[])

        text = query if isinstance(query, str) else str(query.content)
        text = text.strip()
        if not text:
            return MemoryQueryResult(results=[])

        pool = await fetch_optional_pool()
        if pool is None:
            return MemoryQueryResult(results=[])

        try:
            embedding = await get_embedding_service().embed_text(text)
            async with pool.acquire() as conn:
                rows = await list_relevant_memories(
                    conn,
                    user_id=self._user_id,  # type: ignore[arg-type] - _enabled 保证非 None
                    embedding=embedding,
                    limit=kwargs.get("limit") or get_settings().memory_retrieval_limit,
                )
        except Exception:
            # 记忆召回失败不能拖垮回答，降级成"没有记忆"。
            logger.exception("长期记忆召回失败，本轮降级为无记忆上下文")
            return MemoryQueryResult(results=[])

        return MemoryQueryResult(
            results=[
                MemoryContent(
                    content=row["content"],
                    mime_type=MemoryMimeType.TEXT,
                    metadata={
                        "memory_id": row.get("id"),
                        "memory_type": row.get("memory_type") or DEFAULT_MEMORY_TYPE,
                        "importance": row.get("importance"),
                        "score": row.get("score"),
                        **(_as_dict(row.get("metadata"))),
                    },
                )
                for row in rows
            ]
        )

    async def add(
        self, content: MemoryContent, cancellation_token: CancellationToken | None = None
    ) -> None:
        """写入一条长期记忆。

        `content.metadata` 里可带 `memory_type` / `importance` / `tags` /
        `source_session_id`；缺省时落到 fact / 0.7。
        """
        if not self._enabled or not get_settings().storage_active:
            return

        text = str(content.content).strip()
        if not text:
            return

        meta = dict(content.metadata or {})
        memory_type = str(meta.pop("memory_type", DEFAULT_MEMORY_TYPE))
        if memory_type not in MEMORY_TYPES:
            logger.warning("未知记忆类型 %r，回退为 %s", memory_type, DEFAULT_MEMORY_TYPE)
            memory_type = DEFAULT_MEMORY_TYPE
        importance = _clamp_importance(meta.pop("importance", DEFAULT_IMPORTANCE))
        source_session_id = meta.pop("source_session_id", None)

        pool = await fetch_optional_pool()
        if pool is None:
            return

        try:
            embedding = await get_embedding_service().embed_text(text)
            async with pool.acquire() as conn:
                await insert_memory(
                    conn,
                    user_id=self._user_id,  # type: ignore[arg-type]
                    content=text,
                    embedding=embedding,
                    memory_type=memory_type,
                    importance=importance,
                    source_session_id=source_session_id,
                    metadata=meta,
                )
        except Exception:
            # 记忆写入是"锦上添花"，失败不该影响本次回答。
            logger.exception("长期记忆写入失败")

    async def add_text(self, text: str, *, metadata: dict[str, Any] | None = None) -> None:
        """Business-facing convenience method that keeps AutoGen types in engine/."""
        await self.add(
            MemoryContent(
                content=text,
                mime_type=MemoryMimeType.TEXT,
                metadata=metadata,
            )
        )

    async def clear(self) -> None:
        # 清空记忆是破坏性操作，必须走带确认的记忆管理接口（/api/memories），
        # 不该由 Agent 在对话中间随手触发。
        raise NotImplementedError(
            "长期记忆不支持经 Memory.clear 批量清空；请走记忆管理接口 /api/memories。"
        )

    async def close(self) -> None:
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _clamp_importance(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return DEFAULT_IMPORTANCE
    return min(1.0, max(0.0, number))

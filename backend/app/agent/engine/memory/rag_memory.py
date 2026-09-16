"""知识库检索接进 AutoGen Memory 协议。

内部走的是项目原有的 `retrieve_rag_context()`——向量 + 全文 + RRF + rerank + MMR +
相邻块扩展，含中文 bigram 分词修复。**检索管线一行不改**，这里只做协议适配。
"""

from __future__ import annotations

import logging
import time
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
    BLOCK_KEY_KNOWLEDGE,
    inject_system_block,
    latest_user_query,
    run_query_once_per_turn,
)
from app.agent.engine.turn_context import current_turn_state
from app.agent.rag.relevance import should_retrieve_documents
from app.agent.rag.service import retrieve_rag_context
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool

logger = logging.getLogger(__name__)


class RagMemory(Memory):
    """知识库文档检索。

    Args:
        user_id: 检索归属用户；None 表示无身份（检索仍会按公开范围执行，由 SQL 层决定）。
        enabled: 对应请求里的 `use_rag`。关闭时所有方法都是 no-op。
    """

    component_type = "memory"

    def __init__(self, *, user_id: str | None, enabled: bool = True) -> None:
        self._user_id = user_id
        self._enabled = enabled

    async def update_context(self, model_context: ChatCompletionContext) -> UpdateContextResult:
        query = await latest_user_query(model_context)
        if not query:
            return UpdateContextResult(memories=MemoryQueryResult(results=[]))

        # 回合级缓存：工具循环里每次模型调用都会走到这里，但检索词没变。
        result = await run_query_once_per_turn(
            BLOCK_KEY_KNOWLEDGE, query, lambda: self.query(query)
        )
        if not result.results:
            # 这轮没检索到就把上一轮的块清掉：多步链路里每次发言都会重查，
            # 留着旧块等于拿上一步的资料回答这一步的问题。
            await inject_system_block(model_context, "", key=BLOCK_KEY_KNOWLEDGE)
            return UpdateContextResult(memories=MemoryQueryResult(results=[]))

        # 检索结果已由 formatter 组织成带来源标注的块，直接整体注入
        await inject_system_block(
            model_context, str(result.results[0].content), key=BLOCK_KEY_KNOWLEDGE
        )
        return UpdateContextResult(memories=result)

    async def query(
        self,
        query: str | MemoryContent,
        cancellation_token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> MemoryQueryResult:
        if not self._enabled:
            return MemoryQueryResult(results=[])

        text = query if isinstance(query, str) else str(query.content)
        text = text.strip()
        if not text or not get_settings().storage_active:
            return MemoryQueryResult(results=[])

        if not should_retrieve_documents(text):
            self._record_trace(retrieved_chunks=0, trace={"use_rag": True, "skipped": True, "reason": "task_not_document_related", "context_chars": 0})
            return MemoryQueryResult(results=[])

        pool = await fetch_optional_pool()
        if pool is None:
            return MemoryQueryResult(results=[])

        trace: dict[str, Any] = {"use_rag": True, "query_chars": len(text)}
        try:
            started = time.perf_counter()
            embedding = await get_embedding_service().embed_text(text)
            trace["embedding_ms"] = int((time.perf_counter() - started) * 1000)

            rag = await retrieve_rag_context(
                pool,
                query=text,
                embedding=embedding,
                user_id=self._user_id,
                trace=trace,
            )
        except Exception:
            # 检索失败不能拖垮回答：降级成"没检索到"，如实反映在 trace 里。
            logger.exception("RAG 检索失败，本轮降级为无知识库上下文")
            trace["error"] = "rag_failed"
            self._record_trace(retrieved_chunks=0, trace=trace)
            return MemoryQueryResult(results=[])

        self._record_trace(retrieved_chunks=rag.retrieved_chunks, trace=rag.trace)
        if not rag.context:
            return MemoryQueryResult(results=[])

        return MemoryQueryResult(
            results=[
                MemoryContent(
                    content=rag.context,
                    mime_type=MemoryMimeType.MARKDOWN,
                    metadata={
                        "source": "knowledge_base",
                        "retrieved_chunks": rag.retrieved_chunks,
                    },
                )
            ]
        )

    def _record_trace(self, *, retrieved_chunks: int, trace: dict | None) -> None:
        # 检索命中数与 trace 要经 SSE 回到前端（rag_trace 面板），
        # 但 Memory 协议没有返回值通道，只能走回合级状态。
        state = current_turn_state()
        if state is not None:
            state.record_retrieval(retrieved_chunks=retrieved_chunks, trace=trace)

    async def add(
        self, content: MemoryContent, cancellation_token: CancellationToken | None = None
    ) -> None:
        # 知识库是只读检索面：入库走文档上传管线（documents/），有解析、切块、
        # 向量化、归属校验一整套。这里绝不能开一个绕过它们的旁路写入口。
        raise NotImplementedError(
            "知识库不支持经 Memory.add 写入；请走文档上传接口（/api/documents），"
            "那条路径才有解析、切块、向量化与归属校验。"
        )

    async def clear(self) -> None:
        raise NotImplementedError("知识库不支持经 Memory.clear 清空；请走文档管理接口。")

    async def close(self) -> None:
        # 连接池由 app.db.pool 统一管理，生命周期跟着应用走，这里不该关它。
        return None

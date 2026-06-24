from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.agent.rag.formatter import format_retrieved_blocks
from app.agent.rag.mmr import mmr_select
from app.agent.rerank import get_rerank_service
from app.db.repositories.document import fetch_adjacent_chunks
from app.db.repositories.vector_search import search_hybrid_rrf
from app.core.settings import get_settings


@dataclass(frozen=True)
class RAGResult:
    context: str | None
    retrieved_chunks: int
    trace: dict[str, Any]


async def retrieve_rag_context(
    pool,
    *,
    query: str,
    embedding: list[float],
    user_id: str | None,
    trace: dict[str, Any],
    search_fn: Callable[..., Awaitable[list[dict[str, Any]]]] = search_hybrid_rrf,
) -> RAGResult:
    settings = get_settings()
    started = time.perf_counter()
    async with pool.acquire() as conn:
        chunks = await search_fn(
            conn,
            embedding=embedding,
            query=query,
            limit=max(settings.rag_candidate_limit, settings.rag_retrieval_limit),
            k=settings.rag_rrf_k,
            user_id=user_id,
        )
    trace["candidates"] = len(chunks)
    trace["recall_ms"] = int((time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    chunks = await get_rerank_service().rerank(
        query=query,
        items=chunks,
        top_n=(settings.rerank_top_n or settings.rag_retrieval_limit) + 3,
    )
    trace["rerank_ms"] = int((time.perf_counter() - started) * 1000)
    if settings.rag_mmr_enabled:
        chunks = await asyncio.to_thread(
            mmr_select,
            candidates=chunks,
            query_embedding=embedding,
            top_n=settings.rerank_top_n or settings.rag_retrieval_limit,
            lambda_mult=settings.rag_mmr_lambda,
        )
        trace["mmr_selected"] = len(chunks)
    else:
        chunks = chunks[: settings.rerank_top_n or settings.rag_retrieval_limit]
    # 上下文链接：给每个锚点块补回相邻块（±radius），修复"命中孤立块、跨块论述被切断"。
    # 仅当开启且有归属用户时执行；失败不影响主链路（降级为纯锚点块）。
    if settings.rag_context_expansion_enabled and user_id:
        try:
            chunks = await _expand_context(
                pool,
                chunks=chunks,
                user_id=user_id,
                radius=settings.rag_context_expansion_radius,
                trace=trace,
            )
        except Exception:
            trace["expansion_error"] = True
    retrieved_chunks = sum(1 for chunk in chunks if str(chunk.get("content") or "").strip())
    return RAGResult(
        context=format_retrieved_blocks(chunks, title="document"),
        retrieved_chunks=retrieved_chunks,
        trace=trace,
    )


async def _expand_context(
    pool,
    *,
    chunks: list[dict[str, Any]],
    user_id: str,
    radius: int,
    trace: dict[str, Any],
) -> list[dict[str, Any]]:
    """给每个锚点块补回同文档内 chunk_index±radius 的相邻块，拼接成"扩展块"。

    设计要点：
    - 按 document_id 分组、按 chunk_index 排序去重合并，绝不跨文档串内容；
    - 一个文档内多个锚点的扩展窗口重叠时合并去重（同一块不重复拼接）；
    - 保留锚点的 score/metadata（面包屑取最靠前锚点的），formatter 无需改动；
    - 命中首/末块时只补存在的一侧，缺失序号被 SQL 自然忽略，不越界。
    """
    if radius <= 0 or not chunks:
        return chunks

    # 1) 收集每个文档需要的块序号集合（锚点 ± radius），并记录锚点自身。
    wanted: dict[str, set[int]] = {}
    anchors: dict[str, list[int]] = {}
    for chunk in chunks:
        doc_id = chunk.get("document_id")
        meta = chunk.get("metadata")
        idx = _chunk_index_of(chunk)
        if doc_id is None or idx is None:
            continue
        doc_id = str(doc_id)
        wanted.setdefault(doc_id, set()).update(range(idx - radius, idx + radius + 1))
        anchors.setdefault(doc_id, []).append(idx)

    if not wanted:
        return chunks

    # 2) 批量取每个文档的相邻块（含锚点本身），按 chunk_index 升序。
    fetched: dict[str, list[dict[str, Any]]] = {}
    async with pool.acquire() as conn:
        for doc_id, indices in wanted.items():
            fetched[doc_id] = await fetch_adjacent_chunks(
                conn,
                document_id=doc_id,
                indices=sorted(i for i in indices if i >= 0),
                user_id=user_id,
            )

    # 3) 每个锚点块替换为"该文档全部取回块按序拼接"的扩展块；同文档只产出一个扩展块，
    #    挂在该文档最靠前的锚点上，保留其 score/metadata；其余同文档锚点丢弃（已被合并）。
    expanded: list[dict[str, Any]] = []
    emitted_docs: set[str] = set()
    total_neighbors = 0
    for chunk in chunks:
        doc_id = chunk.get("document_id")
        if doc_id is None:
            expanded.append(chunk)
            continue
        doc_id = str(doc_id)
        if doc_id in emitted_docs:
            continue
        pieces = fetched.get(doc_id) or []
        if not pieces:
            expanded.append(chunk)
            emitted_docs.add(doc_id)
            continue
        merged_text = _dedupe_join(piece.get("content") for piece in pieces)
        total_neighbors += max(0, len(pieces) - len(set(anchors.get(doc_id, []))))
        merged = dict(chunk)
        merged["content"] = merged_text
        expanded.append(merged)
        emitted_docs.add(doc_id)

    trace["expanded_neighbors"] = total_neighbors
    trace["expanded_blocks"] = len(expanded)
    return expanded


def _chunk_index_of(chunk: dict[str, Any]) -> int | None:
    """从块里取 chunk_index：召回行带顶层 chunk_index，否则回退 metadata.chunk_index。"""
    for value in (chunk.get("chunk_index"), _meta_chunk_index(chunk.get("metadata"))):
        if isinstance(value, int):
            return value
    return None


def _meta_chunk_index(metadata: Any) -> Any:
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except json.JSONDecodeError:
            return None
    if isinstance(metadata, dict):
        return metadata.get("chunk_index")
    return None


def _dedupe_join(texts) -> str:
    """按出现顺序拼接文本，跳过空串与完全重复段，相邻块用换行分隔。"""
    seen: set[str] = set()
    parts: list[str] = []
    for text in texts:
        cleaned = str(text or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        parts.append(cleaned)
    return "\n".join(parts)

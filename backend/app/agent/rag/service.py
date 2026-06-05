from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.agent.rag.formatter import format_retrieved_blocks
from app.agent.rag.mmr import mmr_select
from app.agent.rerank import get_rerank_service
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
        chunks = mmr_select(
            candidates=chunks,
            query_embedding=embedding,
            top_n=settings.rerank_top_n or settings.rag_retrieval_limit,
            lambda_mult=settings.rag_mmr_lambda,
        )
        trace["mmr_selected"] = len(chunks)
    else:
        chunks = chunks[: settings.rerank_top_n or settings.rag_retrieval_limit]
    retrieved_chunks = sum(1 for chunk in chunks if str(chunk.get("content") or "").strip())
    return RAGResult(
        context=format_retrieved_blocks(chunks, title="document"),
        retrieved_chunks=retrieved_chunks,
        trace=trace,
    )

from __future__ import annotations

import logging
import time
from typing import Any

from app.lib.db.vector import decode_vector, encode_vector
from app.shared.logging import log_event

logger = logging.getLogger(__name__)


async def search_vector_only(
    conn,
    *,
    embedding: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id::text, document_id::text, content, metadata, embedding::text AS embedding,
               1 - (embedding <=> $1::vector) AS vector_score
        FROM public.document_chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """,
        encode_vector(embedding),
        limit,
    )
    return [_normalize_row(row) for row in rows]


async def search_tsv_only(
    conn,
    *,
    query: str,
    limit: int,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    rows = await conn.fetch(
        """
        SELECT id::text, document_id::text, content, metadata,
               ts_rank_cd(content_tsv, plainto_tsquery('simple', $1)) AS text_score
        FROM public.document_chunks
        WHERE content_tsv @@ plainto_tsquery('simple', $1)
        ORDER BY text_score DESC
        LIMIT $2
        """,
        query,
        limit,
    )
    return [_normalize_row(row) for row in rows]


async def search_hybrid_rrf(
    conn,
    *,
    embedding: list[float],
    query: str,
    limit: int,
    k: int = 60,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    if not query.strip():
        results = await search_vector_only(conn, embedding=embedding, limit=limit)
        log_event(
            logger,
            "rag.recall",
            vector_top=len(results),
            tsv_top=0,
            fused=len(results),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return results

    vector_rows = await search_vector_only(conn, embedding=embedding, limit=limit)
    tsv_rows = await search_tsv_only(conn, query=query, limit=limit)
    fused = _rrf_fuse(vector_rows, tsv_rows, k=k)
    results = fused[:limit]
    log_event(
        logger,
        "rag.recall",
        vector_top=len(vector_rows),
        tsv_top=len(tsv_rows),
        fused=len(results),
        elapsed_ms=int((time.perf_counter() - started) * 1000),
    )
    return results


async def search_document_chunks(
    conn,
    *,
    embedding: list[float],
    query: str,
    limit: int,
    hybrid_with_tsv: bool = True,
) -> list[dict[str, Any]]:
    if hybrid_with_tsv:
        return await search_hybrid_rrf(conn, embedding=embedding, query=query, limit=limit)
    return await search_vector_only(conn, embedding=embedding, limit=limit)


def _rrf_fuse(
    vector_rows: list[dict[str, Any]],
    tsv_rows: list[dict[str, Any]],
    *,
    k: int,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for rows, source in ((vector_rows, "vector"), (tsv_rows, "tsv")):
        for rank, row in enumerate(rows, start=1):
            row_id = str(row["id"])
            current = by_id.setdefault(row_id, dict(row))
            current.setdefault("rrf_sources", [])
            current["rrf_sources"].append(source)
            current["rrf_score"] = float(current.get("rrf_score") or 0) + 1 / (k + rank)
            if row.get("vector_score") is not None:
                current["vector_score"] = row["vector_score"]
            if row.get("text_score") is not None:
                current["text_score"] = row["text_score"]
            if row.get("embedding") is not None:
                current["embedding"] = row["embedding"]
    return sorted(by_id.values(), key=lambda item: float(item.get("rrf_score") or 0), reverse=True)


def _normalize_row(row: Any) -> dict[str, Any]:
    value = dict(row)
    if "embedding" in value:
        value["embedding"] = decode_vector(value["embedding"])
    return value

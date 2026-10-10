from __future__ import annotations

import logging
import time
from typing import Any

from app.db.vector import decode_vector, encode_vector
from app.db.repositories._pg.hnsw import fetch_tenant_nearest
from app.core.logging import log_event

logger = logging.getLogger(__name__)


async def search_vector_only(
    conn,
    *,
    embedding: list[float],
    limit: int,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    # user_id 缺失时拒绝返回（防跨租户泄漏，M1）：无归属约束的全库召回是安全漏洞。
    if not user_id:
        return []
    # G9：租户过滤的近邻检索。sql_index 让计划器可用 HNSW（pgvector>=0.8 由
    # fetch_tenant_nearest 开启 iterative_scan 保证过滤后取满 LIMIT；<0.8 时
    # 调大 ef_search 并在不足时回退 sql_exact 精确扫描），sql_exact 先物化
    # 租户数据再排序，召回精确、不依赖计划器选择。
    sql_index = """
        SELECT c.id::text, c.document_id::text, c.chunk_index, c.content, c.metadata,
               c.embedding::text AS embedding,
               1 - (c.embedding <=> $1::vector) AS vector_score
        FROM public.document_chunks c
        WHERE c.embedding IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM public.documents d
              WHERE d.id = c.document_id AND d.created_by_user_id = $2
          )
        ORDER BY c.embedding <=> $1::vector, c.id
        LIMIT $3
        """
    sql_exact = """
        WITH owned AS MATERIALIZED (
            SELECT c.id, c.document_id, c.chunk_index, c.content, c.metadata, c.embedding
            FROM public.document_chunks c
            JOIN public.documents d ON d.id = c.document_id
            WHERE d.created_by_user_id = $2 AND c.embedding IS NOT NULL
        )
        SELECT id::text, document_id::text, chunk_index, content, metadata, embedding::text AS embedding,
               1 - (embedding <=> $1::vector) AS vector_score
        FROM owned
        ORDER BY embedding <=> $1::vector, id
        LIMIT $3
        """
    rows = await fetch_tenant_nearest(
        conn,
        sql_index=sql_index,
        sql_exact=sql_exact,
        params=(encode_vector(embedding), user_id, limit),
        limit=limit,
    )
    return [_normalize_row(row) for row in rows]


async def search_tsv_only(
    conn,
    *,
    query: str,
    limit: int,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    # user_id 缺失时拒绝返回（防跨租户泄漏，M1）。
    if not user_id:
        return []
    # CJK 全文：用 agent_rs.to_cjk_tsquery（重叠二字组），与 content_tsv 的同款 bigram 写入对称匹配。
    # 旧 plainto_tsquery('simple') 不切中文，中文查询命中率≈0；见 migration 0010。
    # 同时 SELECT embedding：让纯 tsv 命中的块也带向量，使下游 MMR 多样性对全文命中生效
    # （否则 _rrf_fuse 复制不到 embedding，MMR 的 _cosine 退化为 0）。
    sql = """
        SELECT c.id::text, c.document_id::text, c.chunk_index, c.content, c.metadata,
               c.embedding::text AS embedding,
               ts_rank_cd(c.content_tsv, agent_rs.to_cjk_tsquery($1)) AS text_score
        FROM public.document_chunks c
        JOIN public.documents d ON d.id = c.document_id
        WHERE c.content_tsv @@ agent_rs.to_cjk_tsquery($1)
        AND d.created_by_user_id = $2
        ORDER BY text_score DESC
        LIMIT $3
        """
    rows = await conn.fetch(sql, query, user_id, limit)
    return [_normalize_row(row) for row in rows]


async def search_hybrid_rrf(
    conn,
    *,
    embedding: list[float],
    query: str,
    limit: int,
    k: int = 60,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    if not query.strip():
        results = await search_vector_only(conn, embedding=embedding, limit=limit, user_id=user_id)
        log_event(
            logger,
            "rag.recall",
            vector_top=len(results),
            tsv_top=0,
            fused=len(results),
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )
        return results

    vector_rows = await search_vector_only(conn, embedding=embedding, limit=limit, user_id=user_id)
    tsv_rows = await search_tsv_only(conn, query=query, limit=limit, user_id=user_id)
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
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    if hybrid_with_tsv:
        return await search_hybrid_rrf(conn, embedding=embedding, query=query, limit=limit, user_id=user_id)
    return await search_vector_only(conn, embedding=embedding, limit=limit, user_id=user_id)


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

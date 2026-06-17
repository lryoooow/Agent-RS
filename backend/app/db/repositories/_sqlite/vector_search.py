from __future__ import annotations

import logging
import time
from typing import Any

from app.core.logging import log_event
from app.db.vector import decode_vector, encode_vector
# 复用 _pg 实现里的纯 Python RRF 融合，逻辑与 PG 完全一致，不重复造。
from app.db.repositories._pg.vector_search import _rrf_fuse

logger = logging.getLogger(__name__)

try:  # numpy 已是项目依赖
    import numpy as np
except Exception:  # pragma: no cover - numpy 缺失时退化为纯 Python
    np = None


def _cosine_scores(query: list[float], matrix: list[list[float]]) -> list[float]:
    """批量余弦相似度。numpy 可用走向量化，否则纯 Python 兜底。"""
    if np is not None:
        q = np.asarray(query, dtype="float32")
        m = np.asarray(matrix, dtype="float32")
        q_norm = np.linalg.norm(q)
        m_norm = np.linalg.norm(m, axis=1)
        denom = m_norm * q_norm
        denom[denom == 0] = 1e-12
        return (m @ q / denom).tolist()
    scores: list[float] = []
    q_norm = sum(v * v for v in query) ** 0.5 or 1e-12
    for vec in matrix:
        dot = sum(a * b for a, b in zip(query, vec))
        v_norm = sum(v * v for v in vec) ** 0.5 or 1e-12
        scores.append(dot / (v_norm * q_norm))
    return scores


async def _load_candidate_chunks(conn, *, user_id: str | None) -> list[dict[str, Any]]:
    """取出带 embedding 的候选 chunk（含原始向量），供暴力余弦排序。"""
    if user_id:
        sql = """
            SELECT c.id, c.document_id, c.content, c.metadata, c.embedding
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.created_by_user_id = ? AND c.embedding IS NOT NULL AND c.embedding != ''
        """
        rows = await conn.fetch(sql, user_id)
    else:
        sql = """
            SELECT c.id, c.document_id, c.content, c.metadata, c.embedding
            FROM document_chunks c
            WHERE c.embedding IS NOT NULL AND c.embedding != ''
        """
        rows = await conn.fetch(sql)
    return [dict(row) for row in rows]


async def search_vector_only(
    conn,
    *,
    embedding: list[float],
    limit: int,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    candidates = await _load_candidate_chunks(conn, user_id=user_id)
    if not candidates:
        return []
    vectors = [decode_vector(row["embedding"]) or [] for row in candidates]
    # 维度不匹配的脏向量剔除，避免余弦计算崩。
    dim = len(embedding)
    paired = [(row, vec) for row, vec in zip(candidates, vectors) if len(vec) == dim]
    if not paired:
        return []
    scores = _cosine_scores(embedding, [vec for _, vec in paired])
    ranked = sorted(zip(paired, scores), key=lambda item: item[1], reverse=True)[:limit]
    results: list[dict[str, Any]] = []
    for (row, vec), score in ranked:
        results.append(
            {
                "id": row["id"],
                "document_id": row["document_id"],
                "content": row["content"],
                "metadata": row["metadata"],
                "embedding": vec,
                "vector_score": float(score),
            }
        )
    return results


def _fts_match_query(query: str) -> str:
    """把用户查询转成 FTS5 安全的 MATCH 串：按空白切词，每词加双引号转义。"""
    tokens = [tok.replace('"', '""') for tok in query.split() if tok.strip()]
    if not tokens:
        return ""
    return " OR ".join(f'"{tok}"' for tok in tokens)


async def search_tsv_only(
    conn,
    *,
    query: str,
    limit: int,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    if not query.strip():
        return []
    # trigram 分词要求 token ≥3 字符；过短查询 FTS 命中为空，退回 LIKE 子串匹配。
    match_query = _fts_match_query(query) if len(query.strip()) >= 3 else ""
    if match_query:
        rows = await _search_fts(conn, match_query=match_query, limit=limit, user_id=user_id)
        if rows:
            return rows
    return await _search_like(conn, query=query, limit=limit, user_id=user_id)


async def _search_fts(
    conn,
    *,
    match_query: str,
    limit: int,
    user_id: str | None,
) -> list[dict[str, Any]]:
    # bm25() 越小越相关，取负值作为 text_score（越大越相关），与 PG ts_rank_cd 方向一致。
    if user_id:
        sql = """
            SELECT c.id, c.document_id, c.content, c.metadata,
                   -bm25(document_chunks_fts) AS text_score
            FROM document_chunks_fts f
            JOIN document_chunks c ON c.rowid = f.rowid
            JOIN documents d ON d.id = c.document_id
            WHERE document_chunks_fts MATCH ? AND d.created_by_user_id = ?
            ORDER BY text_score DESC
            LIMIT ?
        """
        rows = await conn.fetch(sql, match_query, user_id, limit)
    else:
        sql = """
            SELECT c.id, c.document_id, c.content, c.metadata,
                   -bm25(document_chunks_fts) AS text_score
            FROM document_chunks_fts f
            JOIN document_chunks c ON c.rowid = f.rowid
            WHERE document_chunks_fts MATCH ?
            ORDER BY text_score DESC
            LIMIT ?
        """
        rows = await conn.fetch(sql, match_query, limit)
    return [dict(row) for row in rows]


async def _search_like(
    conn,
    *,
    query: str,
    limit: int,
    user_id: str | None,
) -> list[dict[str, Any]]:
    like = f"%{query.strip()}%"
    if user_id:
        sql = """
            SELECT c.id, c.document_id, c.content, c.metadata, 0.0 AS text_score
            FROM document_chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE c.content LIKE ? AND d.created_by_user_id = ?
            LIMIT ?
        """
        rows = await conn.fetch(sql, like, user_id, limit)
    else:
        sql = """
            SELECT c.id, c.document_id, c.content, c.metadata, 0.0 AS text_score
            FROM document_chunks c
            WHERE c.content LIKE ?
            LIMIT ?
        """
        rows = await conn.fetch(sql, like, limit)
    return [dict(row) for row in rows]


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

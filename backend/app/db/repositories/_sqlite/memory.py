from __future__ import annotations

import json
import uuid
from typing import Any

from app.db.sanitize import parse_jsonb, sanitize_json, sanitize_text
from app.db.vector import decode_vector, encode_vector
from app.db.repositories._sqlite.vector_search import _cosine_scores


async def list_relevant_memories(
    conn,
    *,
    user_id: str,
    embedding: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    # `embedding <=> ?` 余弦排序无 SQLite 对应，取出后暴力余弦排序取 TopN。
    rows = await conn.fetch(
        """
        SELECT id, content, memory_type, importance, metadata, embedding
        FROM memories
        WHERE user_id = ?
          AND embedding IS NOT NULL AND embedding != ''
        """,
        user_id,
    )
    if not rows:
        return []
    dim = len(embedding)
    candidates: list[tuple[dict[str, Any], list[float]]] = []
    for row in rows:
        vec = decode_vector(row["embedding"]) or []
        if len(vec) == dim:
            candidates.append((dict(row), vec))
    if not candidates:
        return []
    scores = _cosine_scores(embedding, [vec for _, vec in candidates])
    ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)[:limit]
    results: list[dict[str, Any]] = []
    for (row, _vec), score in ranked:
        results.append(
            {
                "id": row["id"],
                "content": row["content"],
                "memory_type": row["memory_type"],
                "importance": row["importance"],
                "metadata": row["metadata"],
                "score": float(score),
            }
        )
    return results


async def insert_memory(
    conn,
    *,
    user_id: str,
    content: str,
    embedding: list[float] | None,
    memory_type: str = "fact",
    importance: float = 0.7,
    source_session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    memory_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO memories (
          id, user_id, content, embedding, memory_type, importance, source_session_id, metadata
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        memory_id,
        user_id,
        sanitize_text(content),
        encode_vector(embedding) if embedding else None,
        memory_type,
        importance,
        source_session_id,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
    )
    return memory_id


async def list_memories(conn, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id, content, memory_type, importance, metadata, created_at
        FROM memories
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        user_id,
        limit,
    )
    return [{**dict(row), "metadata": parse_jsonb(row["metadata"])} for row in rows]


async def delete_memory(conn, *, user_id: str, memory_id: str) -> bool:
    rowcount = await conn.execute(
        "DELETE FROM memories WHERE id = ? AND user_id = ?",
        memory_id,
        user_id,
    )
    return rowcount == 1

from __future__ import annotations

import json
from typing import Any

from app.lib.db.sanitize import sanitize_json, sanitize_text
from app.lib.db.vector import encode_vector


async def list_relevant_memories(
    conn,
    *,
    user_id: str,
    embedding: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id::text, content, memory_type, importance, metadata,
               1 - (embedding <=> $2::vector) AS score
        FROM public.memories
        WHERE user_id = $1
          AND embedding IS NOT NULL
        ORDER BY embedding <=> $2::vector
        LIMIT $3
        """,
        user_id,
        encode_vector(embedding),
        limit,
    )
    return [dict(row) for row in rows]


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
    row = await conn.fetchrow(
        """
        INSERT INTO public.memories (
          user_id, content, embedding, memory_type, importance, source_session_id, metadata
        )
        VALUES ($1, $2, $3::vector, $4, $5, $6, $7::jsonb)
        RETURNING id::text
        """,
        user_id,
        sanitize_text(content),
        encode_vector(embedding) if embedding else None,
        memory_type,
        importance,
        source_session_id,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
    )
    return row["id"]


async def list_memories(conn, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT id::text, content, memory_type, importance, metadata, created_at
        FROM public.memories
        WHERE user_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        user_id,
        limit,
    )
    return [dict(row) for row in rows]


async def delete_memory(conn, *, user_id: str, memory_id: str) -> bool:
    result = await conn.execute(
        "DELETE FROM public.memories WHERE id = $1 AND user_id = $2",
        memory_id,
        user_id,
    )
    return result.endswith(" 1")

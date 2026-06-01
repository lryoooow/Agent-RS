from __future__ import annotations

import json
import uuid
from typing import Any

from app.lib.db.sanitize import sanitize_json, sanitize_text
from app.lib.db.vector import encode_vector
from app.schemas.chat import ChatMessage


async def append_message(
    conn,
    *,
    conversation_id: str,
    role: str,
    content: str,
    status: str = "complete",
    metadata: dict[str, Any] | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
) -> str:
    message_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO chatbot.messages (
          id, conversation_id, role, content, status, metadata_json, tokens_in, tokens_out
        )
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7, $8)
        """,
        message_id,
        conversation_id,
        role,
        sanitize_text(content),
        status,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
        tokens_in,
        tokens_out,
    )
    return message_id


async def update_message_complete(
    conn,
    *,
    message_id: str,
    content: str,
    status: str = "complete",
    metadata: dict[str, Any] | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
) -> None:
    await conn.execute(
        """
        UPDATE chatbot.messages
        SET content = $2,
            status = $3,
            metadata_json = metadata_json || $4::jsonb,
            tokens_in = COALESCE($5, tokens_in),
            tokens_out = COALESCE($6, tokens_out)
        WHERE id = $1::uuid
        """,
        message_id,
        sanitize_text(content),
        status,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
        tokens_in,
        tokens_out,
    )


async def set_embedding(conn, *, message_id: str, embedding: list[float]) -> None:
    await conn.execute(
        "UPDATE chatbot.messages SET embedding = $2::vector WHERE id = $1::uuid",
        message_id,
        encode_vector(embedding),
    )


async def add_embedding_retry(conn, *, message_id: str, error: str) -> None:
    # TODO: add a background consumer so this queue cannot grow without bound.
    await conn.execute(
        """
        INSERT INTO public.embedding_retry (message_id, attempts, last_error, last_attempt_at)
        VALUES ($1::uuid, 1, $2, now())
        """,
        message_id,
        error[:4000],
    )


async def list_recent_messages(conn, *, conversation_id: str, limit: int) -> list[ChatMessage]:
    rows = await conn.fetch(
        """
        SELECT role, content
        FROM chatbot.messages
        WHERE conversation_id = $1::uuid
          AND status = 'complete'
          AND role IN ('user', 'assistant', 'system')
        ORDER BY created_at DESC
        LIMIT $2
        """,
        conversation_id,
        limit,
    )
    return [
        ChatMessage(role=row["role"], content=row["content"])
        for row in reversed(rows)
        if row["content"].strip()
    ]


async def list_conversation_messages(
    conn,
    *,
    conversation_id: str,
    limit: int = 100,
    before: str | None = None,
) -> list[dict[str, Any]]:
    before_clause = "AND id < $3::uuid" if before else ""
    params: list[Any] = [conversation_id, limit]
    if before:
        params.append(before)
    rows = await conn.fetch(
        f"""
        SELECT id::text, role, content, status, metadata_json, tokens_in, tokens_out, created_at
        FROM chatbot.messages
        WHERE conversation_id = $1::uuid
          {before_clause}
        ORDER BY created_at DESC
        LIMIT $2
        """,
        *params,
    )
    return [dict(row) for row in reversed(rows)]

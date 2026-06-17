from __future__ import annotations

import json
import uuid
from typing import Any

from app.db.sanitize import parse_jsonb, sanitize_json, sanitize_text
from app.db.vector import encode_vector
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
        INSERT INTO messages (
          id, conversation_id, role, content, status, metadata_json, tokens_in, tokens_out
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
    # jsonb `||` 合并 → SQLite json_patch(col, ?)；COALESCE 行为一致。
    await conn.execute(
        """
        UPDATE messages
        SET content = ?,
            status = ?,
            metadata_json = json_patch(metadata_json, ?),
            tokens_in = COALESCE(?, tokens_in),
            tokens_out = COALESCE(?, tokens_out)
        WHERE id = ?
        """,
        sanitize_text(content),
        status,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
        tokens_in,
        tokens_out,
        message_id,
    )


async def set_embedding(conn, *, message_id: str, embedding: list[float]) -> None:
    await conn.execute(
        "UPDATE messages SET embedding = ? WHERE id = ?",
        encode_vector(embedding),
        message_id,
    )


async def add_embedding_retry(conn, *, message_id: str, error: str) -> None:
    await conn.execute(
        """
        INSERT INTO embedding_retry (message_id, attempts, last_error, last_attempt_at)
        VALUES (?, 1, ?, CURRENT_TIMESTAMP)
        """,
        message_id,
        error[:4000],
    )


async def list_recent_messages(conn, *, conversation_id: str, limit: int) -> list[ChatMessage]:
    rows = await conn.fetch(
        """
        SELECT role, content
        FROM messages
        WHERE conversation_id = ?
          AND status = 'complete'
          AND role IN ('user', 'assistant', 'system')
        ORDER BY created_at DESC
        LIMIT ?
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
    before_clause = "AND id < ?" if before else ""
    params: list[Any] = [conversation_id]
    if before:
        params.append(before)
    params.append(limit)
    rows = await conn.fetch(
        f"""
        SELECT id, role, content, status, metadata_json, tokens_in, tokens_out, created_at
        FROM messages
        WHERE conversation_id = ?
          {before_clause}
        ORDER BY created_at DESC
        LIMIT ?
        """,
        *params,
    )
    return [{**dict(row), "metadata_json": parse_jsonb(row["metadata_json"])} for row in reversed(rows)]

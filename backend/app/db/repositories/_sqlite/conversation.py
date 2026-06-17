from __future__ import annotations

import uuid
from typing import Any

from app.core.settings import Settings


async def create_conversation(
    conn,
    *,
    user_id: str,
    settings: Settings,
    title: str = "新对话",
    scenario_id: str = "chat_default",
    model_name: str | None = None,
) -> str:
    conversation_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO conversations (
          id, workspace_id, created_by_user_id, title, scenario_id, model_name, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, '{}')
        """,
        conversation_id,
        settings.default_workspace_id,
        user_id,
        title,
        scenario_id,
        model_name,
    )
    return conversation_id


async def get_conversation(conn, conversation_id: str, user_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT id, workspace_id, created_by_user_id, title, scenario_id, model_name
        FROM conversations
        WHERE id = ? AND created_by_user_id = ?
        """,
        conversation_id,
        user_id,
    )
    return dict(row) if row else None


async def list_conversations(conn, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT c.id, c.title, c.scenario_id, c.model_name, c.created_at, c.updated_at,
               count(m.id) AS message_count
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        WHERE c.created_by_user_id = ?
        GROUP BY c.id
        ORDER BY c.updated_at DESC
        LIMIT ?
        """,
        user_id,
        limit,
    )
    return [dict(row) for row in rows]


async def update_conversation_title(
    conn,
    *,
    conversation_id: str,
    user_id: str,
    title: str,
) -> bool:
    rowcount = await conn.execute(
        """
        UPDATE conversations
        SET title = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ? AND created_by_user_id = ?
        """,
        title,
        conversation_id,
        user_id,
    )
    return rowcount == 1


async def delete_conversation(conn, *, conversation_id: str, user_id: str) -> bool:
    row = await get_conversation(conn, conversation_id, user_id)
    if row is None:
        return False
    await conn.execute("DELETE FROM messages WHERE conversation_id = ?", conversation_id)
    rowcount = await conn.execute(
        "DELETE FROM conversations WHERE id = ? AND created_by_user_id = ?",
        conversation_id,
        user_id,
    )
    return rowcount == 1


async def touch_conversation(conn, conversation_id: str) -> None:
    await conn.execute(
        "UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        conversation_id,
    )

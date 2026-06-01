from __future__ import annotations

import uuid
from typing import Any

from app.shared.settings import Settings


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
        INSERT INTO chatbot.conversations (
          id, workspace_id, created_by_user_id, title, scenario_id, model_name, metadata_json
        )
        VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, '{}'::jsonb)
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
        SELECT id::text, workspace_id::text, created_by_user_id::text, title, scenario_id, model_name
        FROM chatbot.conversations
        WHERE id = $1::uuid AND created_by_user_id = $2::uuid
        """,
        conversation_id,
        user_id,
    )
    return dict(row) if row else None


async def list_conversations(conn, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT c.id::text, c.title, c.scenario_id, c.model_name, c.created_at, c.updated_at,
               count(m.id)::int AS message_count
        FROM chatbot.conversations c
        LEFT JOIN chatbot.messages m ON m.conversation_id = c.id
        WHERE c.created_by_user_id = $1::uuid
        GROUP BY c.id
        ORDER BY c.updated_at DESC
        LIMIT $2
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
    result = await conn.execute(
        """
        UPDATE chatbot.conversations
        SET title = $3, updated_at = now()
        WHERE id = $1::uuid AND created_by_user_id = $2::uuid
        """,
        conversation_id,
        user_id,
        title,
    )
    return result.endswith(" 1")


async def delete_conversation(conn, *, conversation_id: str, user_id: str) -> bool:
    row = await get_conversation(conn, conversation_id, user_id)
    if row is None:
        return False
    await conn.execute("DELETE FROM chatbot.messages WHERE conversation_id = $1::uuid", conversation_id)
    result = await conn.execute(
        "DELETE FROM chatbot.conversations WHERE id = $1::uuid AND created_by_user_id = $2::uuid",
        conversation_id,
        user_id,
    )
    return result.endswith(" 1")


async def touch_conversation(conn, conversation_id: str) -> None:
    await conn.execute(
        "UPDATE chatbot.conversations SET updated_at = now() WHERE id = $1::uuid",
        conversation_id,
    )

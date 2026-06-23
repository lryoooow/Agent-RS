from __future__ import annotations

import json
import uuid
from typing import Any

from app.db.repositories.analysis_results import collect_analysis_results
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
        INSERT INTO agent_rs.messages (
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
        UPDATE agent_rs.messages
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
        "UPDATE agent_rs.messages SET embedding = $2::vector WHERE id = $1::uuid",
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


async def list_recent_messages(
    conn, *, conversation_id: str, limit: int, user_id: str | None = None
) -> list[ChatMessage]:
    # user_id 非空时 JOIN conversations 加归属过滤，结构性防跨用户拉取他人会话历史（H3）。
    # user_id 为 None 时退回仅按 conversation_id（兼容无状态/无鉴权路径）。
    if user_id:
        rows = await conn.fetch(
            """
            SELECT m.role, m.content
            FROM agent_rs.messages m
            JOIN agent_rs.conversations c ON c.id = m.conversation_id
            WHERE m.conversation_id = $1::uuid
              AND c.created_by_user_id = $2::uuid
              AND m.status = 'complete'
              AND m.role IN ('user', 'assistant', 'system')
            ORDER BY m.created_at DESC
            LIMIT $3
            """,
            conversation_id,
            user_id,
            limit,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT role, content
            FROM agent_rs.messages
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


async def list_recent_analysis_results(
    conn, *, conversation_id: str, user_id: str | None, limit: int = 5
) -> list[dict[str, Any]]:
    """取本对话最近 N 条助手消息里持久化的结构化分析结果（地物分类/检测/NDVI 等）。

    用于跨轮回注："根据刚才的分类结果生成报告"这类追问轮虽未跑工具，也能看到此前真实结果，
    根治"同对话否认已执行分析"。带 user_id 时 JOIN conversations 做归属过滤（复刻
    list_recent_messages 的 H3 隔离）；user_id 为空则拒绝返回（不跨租户泄漏他人结果）。
    只挑 metadata 里含 geospatial_result / tool_result 的助手消息，按时间正序返回。
    """
    if not user_id:
        return []
    rows = await conn.fetch(
        """
        SELECT m.metadata_json
        FROM agent_rs.messages m
        JOIN agent_rs.conversations c ON c.id = m.conversation_id
        WHERE m.conversation_id = $1::uuid
          AND c.created_by_user_id = $2::uuid
          AND m.role = 'assistant'
          AND m.status = 'complete'
        ORDER BY m.created_at DESC
        LIMIT $3
        """,
        conversation_id,
        user_id,
        # 多取些原始行再在 Python 侧筛"含分析结果"的，避免 JSON 谓词的后端差异。
        max(limit * 4, 20),
    )
    return collect_analysis_results([row["metadata_json"] for row in rows], limit=limit)


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
        FROM agent_rs.messages
        WHERE conversation_id = $1::uuid
          {before_clause}
        ORDER BY created_at DESC
        LIMIT $2
        """,
        *params,
    )
    # jsonb 列经 asyncpg 读回为字符串，归一成 dict|None（与写入侧 json.dumps 对称）。
    return [{**dict(row), "metadata_json": parse_jsonb(row["metadata_json"])} for row in reversed(rows)]

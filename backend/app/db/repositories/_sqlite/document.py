from __future__ import annotations

import json
import uuid
from typing import Any

from app.db.sanitize import sanitize_json, sanitize_text
from app.db.vector import encode_vector


async def insert_document(
    conn,
    *,
    title: str,
    content: str,
    source_url: str | None = None,
    doc_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    user_id: str,
) -> str:
    document_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO documents (id, title, content, source_url, doc_type, metadata, created_by_user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        document_id,
        sanitize_text(title),
        sanitize_text(content),
        sanitize_text(source_url) if source_url else None,
        sanitize_text(doc_type) if doc_type else None,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
        user_id,
    )
    return document_id


async def insert_chunks(
    conn,
    *,
    document_id: str,
    chunks: list[tuple[int, str, list[float], int | None, dict[str, Any] | None]],
) -> None:
    for chunk_index, content, embedding, token_count, metadata in chunks:
        await conn.execute(
            """
            INSERT INTO document_chunks (
              id, document_id, chunk_index, content, embedding, token_count, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            str(uuid.uuid4()),
            document_id,
            chunk_index,
            sanitize_text(content),
            encode_vector(embedding),
            token_count,
            json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
        )


async def list_documents(conn, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    # LATERAL（取最新 job）无 SQLite 对应，改两个相关子查询。schema 启动即建全，
    # 故不复制 _pg 的 is_missing_schema_error 容错分支。
    rows = await conn.fetch(
        """
        SELECT
          d.id,
          d.title,
          d.source_url,
          d.doc_type,
          d.metadata,
          d.created_at,
          d.updated_at,
          count(c.id) AS chunk_count,
          (SELECT j.status FROM document_ingest_jobs j
             WHERE j.document_id = d.id AND j.created_by_user_id = ?
             ORDER BY j.created_at DESC LIMIT 1) AS latest_job_status,
          (SELECT j.id FROM document_ingest_jobs j
             WHERE j.document_id = d.id AND j.created_by_user_id = ?
             ORDER BY j.created_at DESC LIMIT 1) AS latest_job_id
        FROM documents d
        LEFT JOIN document_chunks c ON c.document_id = d.id
        WHERE d.created_by_user_id = ?
        GROUP BY d.id
        ORDER BY d.created_at DESC
        LIMIT ?
        """,
        user_id,
        user_id,
        user_id,
        limit,
    )
    return [dict(row) for row in rows]


async def get_document(conn, *, document_id: str, user_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT
          d.id,
          d.title,
          d.content,
          d.source_url,
          d.doc_type,
          d.metadata,
          d.created_at,
          d.updated_at,
          count(c.id) AS chunk_count
        FROM documents d
        LEFT JOIN document_chunks c ON c.document_id = d.id
        WHERE d.id = ? AND d.created_by_user_id = ?
        GROUP BY d.id
        """,
        document_id,
        user_id,
    )
    # LEFT JOIN + GROUP BY 在无匹配文档时仍返回一行全 NULL，需判 id 为空。
    if row is None or row["id"] is None:
        return None
    return dict(row)


async def list_document_chunks(
    conn,
    *,
    document_id: str,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT c.id, c.document_id, c.chunk_index, c.content, c.token_count, c.metadata, c.created_at
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.document_id = ? AND d.created_by_user_id = ?
        ORDER BY c.chunk_index ASC
        LIMIT ? OFFSET ?
        """,
        document_id,
        user_id,
        limit,
        offset,
    )
    return [dict(row) for row in rows]


async def delete_document(conn, *, document_id: str, user_id: str) -> bool:
    await conn.execute(
        """
        DELETE FROM document_chunks
        WHERE document_id = (
          SELECT id FROM documents WHERE id = ? AND created_by_user_id = ?
        )
        """,
        document_id,
        user_id,
    )
    rowcount = await conn.execute(
        "DELETE FROM documents WHERE id = ? AND created_by_user_id = ?",
        document_id,
        user_id,
    )
    return rowcount == 1

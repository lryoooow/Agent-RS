from __future__ import annotations

import json
from typing import Any

from app.db.errors import is_missing_schema_error
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
    row = await conn.fetchrow(
        """
        INSERT INTO public.documents (title, content, source_url, doc_type, metadata, created_by_user_id)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6)
        RETURNING id::text
        """,
        sanitize_text(title),
        sanitize_text(content),
        sanitize_text(source_url) if source_url else None,
        sanitize_text(doc_type) if doc_type else None,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
        user_id,
    )
    return row["id"]


async def insert_chunks(
    conn,
    *,
    document_id: str,
    chunks: list[tuple[int, str, list[float], int | None, dict[str, Any] | None]],
) -> None:
    for chunk_index, content, embedding, token_count, metadata in chunks:
        await conn.execute(
            """
            INSERT INTO public.document_chunks (
              document_id, chunk_index, content, embedding, token_count, metadata
            )
            VALUES (
              $1::uuid, $2, $3, $4::vector, $5, $6::jsonb
            )
            """,
            document_id,
            chunk_index,
            sanitize_text(content),
            encode_vector(embedding),
            token_count,
            json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
        )


async def list_documents(conn, *, user_id: str, limit: int = 100) -> list[dict[str, Any]]:
    try:
        rows = await conn.fetch(
            """
            SELECT
              d.id::text,
              d.title,
              d.source_url,
              d.doc_type,
              d.metadata,
              d.created_at,
              d.updated_at,
              count(c.id)::int AS chunk_count,
              j.status AS latest_job_status,
              j.id::text AS latest_job_id
            FROM public.documents d
            LEFT JOIN public.document_chunks c ON c.document_id = d.id
            LEFT JOIN LATERAL (
              SELECT id, status
              FROM public.document_ingest_jobs
              WHERE document_id = d.id
                AND created_by_user_id = $1
              ORDER BY created_at DESC
              LIMIT 1
            ) j ON true
            WHERE d.created_by_user_id = $1
            GROUP BY d.id, j.status, j.id
            ORDER BY d.created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    except Exception as exc:
        if not is_missing_schema_error(exc):
            raise
        rows = await conn.fetch(
            """
            SELECT
              d.id::text,
              d.title,
              d.source_url,
              d.doc_type,
              d.metadata,
              d.created_at,
              d.updated_at,
              count(c.id)::int AS chunk_count,
              NULL::text AS latest_job_status,
              NULL::text AS latest_job_id
            FROM public.documents d
            LEFT JOIN public.document_chunks c ON c.document_id = d.id
            WHERE d.created_by_user_id = $1
            GROUP BY d.id
            ORDER BY d.created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    return [dict(row) for row in rows]


async def get_document(conn, *, document_id: str, user_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT
          d.id::text,
          d.title,
          d.content,
          d.source_url,
          d.doc_type,
          d.metadata,
          d.created_at,
          d.updated_at,
          count(c.id)::int AS chunk_count
        FROM public.documents d
        LEFT JOIN public.document_chunks c ON c.document_id = d.id
        WHERE d.id = $1::uuid AND d.created_by_user_id = $2
        GROUP BY d.id
        """,
        document_id,
        user_id,
    )
    return dict(row) if row else None


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
        SELECT c.id::text, c.document_id::text, c.chunk_index, c.content,
               c.token_count, c.metadata, c.created_at
        FROM public.document_chunks c
        JOIN public.documents d ON d.id = c.document_id
        WHERE c.document_id = $1::uuid AND d.created_by_user_id = $2
        ORDER BY c.chunk_index ASC
        LIMIT $3 OFFSET $4
        """,
        document_id,
        user_id,
        limit,
        offset,
    )
    return [dict(row) for row in rows]


async def fetch_adjacent_chunks(
    conn,
    *,
    document_id: str,
    indices: list[int],
    user_id: str,
) -> list[dict[str, Any]]:
    """按 (document_id, chunk_index ∈ indices) 批量取块，供检索后的上下文扩展。

    带 user_id 租户约束（JOIN documents 校验归属，与 list_document_chunks 同款鉴权），
    防跨租户读取邻居块。返回按 chunk_index 升序，便于上层按序拼接。
    """
    if not indices:
        return []
    rows = await conn.fetch(
        """
        SELECT c.id::text, c.document_id::text, c.chunk_index, c.content, c.metadata
        FROM public.document_chunks c
        JOIN public.documents d ON d.id = c.document_id
        WHERE c.document_id = $1::uuid
          AND d.created_by_user_id = $2
          AND c.chunk_index = ANY($3::int[])
        ORDER BY c.chunk_index ASC
        """,
        document_id,
        user_id,
        indices,
    )
    return [dict(row) for row in rows]


async def delete_document(conn, *, document_id: str, user_id: str) -> bool:
    await conn.execute(
        """
        DELETE FROM public.document_chunks
        WHERE document_id = (
          SELECT id FROM public.documents WHERE id = $1::uuid AND created_by_user_id = $2
        )
        """,
        document_id,
        user_id,
    )
    result = await conn.execute(
        "DELETE FROM public.documents WHERE id = $1::uuid AND created_by_user_id = $2",
        document_id,
        user_id,
    )
    return result.endswith(" 1")

from __future__ import annotations

import json
import uuid
from typing import Any

from app.db.sanitize import sanitize_json, sanitize_text


async def create_ingest_job(
    conn,
    *,
    filename: str,
    file_size: int,
    temp_path: str,
    metadata: dict[str, Any] | None = None,
    user_id: str,
) -> str:
    job_id = str(uuid.uuid4())
    await conn.execute(
        """
        INSERT INTO document_ingest_jobs (
          id, filename, file_size, temp_path, metadata, created_by_user_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        job_id,
        sanitize_text(filename),
        file_size,
        temp_path,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
        user_id,
    )
    return job_id


async def update_ingest_job(
    conn,
    *,
    job_id: str,
    status: str,
    progress: int,
    doc_type: str | None = None,
    text_length: int | None = None,
    chunk_count: int | None = None,
    embedding_batches: int | None = None,
    document_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    stage_timings: dict[str, Any] | None = None,
) -> None:
    # jsonb `||` 合并 → json_patch；其余 COALESCE 行为与 PG 一致。
    await conn.execute(
        """
        UPDATE document_ingest_jobs
        SET status = ?,
            progress = ?,
            doc_type = COALESCE(?, doc_type),
            text_length = COALESCE(?, text_length),
            chunk_count = COALESCE(?, chunk_count),
            embedding_batches = COALESCE(?, embedding_batches),
            document_id = COALESCE(?, document_id),
            error_code = ?,
            error_message = ?,
            stage_timings = json_patch(stage_timings, ?),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        status,
        progress,
        sanitize_text(doc_type) if doc_type else None,
        text_length,
        chunk_count,
        embedding_batches,
        document_id,
        sanitize_text(error_code) if error_code else None,
        sanitize_text(error_message) if error_message else None,
        json.dumps(sanitize_json(stage_timings or {}), ensure_ascii=False),
        job_id,
    )


async def get_ingest_job(conn, *, job_id: str, user_id: str | None = None) -> dict[str, Any] | None:
    owner_clause = "AND created_by_user_id = ?" if user_id else ""
    params: tuple[Any, ...] = (job_id, user_id) if user_id else (job_id,)
    row = await conn.fetchrow(
        f"""
        SELECT id, status, progress, filename, doc_type, file_size, text_length,
               chunk_count, embedding_batches, document_id, error_code, error_message,
               stage_timings, metadata, created_at, updated_at
        FROM document_ingest_jobs
        WHERE id = ?
        {owner_clause}
        """,
        *params,
    )
    return dict(row) if row else None


async def fail_stale_ingest_jobs(conn) -> None:
    await conn.execute(
        """
        UPDATE document_ingest_jobs
        SET status = 'failed',
            progress = 100,
            error_code = 'JOB_INTERRUPTED',
            error_message = 'Document ingest job was interrupted by server restart.',
            updated_at = CURRENT_TIMESTAMP
        WHERE status IN ('pending', 'parsing', 'chunking', 'embedding', 'inserting')
        """
    )

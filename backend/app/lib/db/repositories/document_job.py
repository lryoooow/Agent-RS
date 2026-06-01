from __future__ import annotations

import json
from typing import Any

from app.lib.db.sanitize import sanitize_json, sanitize_text


async def create_ingest_job(
    conn,
    *,
    filename: str,
    file_size: int,
    temp_path: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    row = await conn.fetchrow(
        """
        INSERT INTO public.document_ingest_jobs (
          filename, file_size, temp_path, metadata
        )
        VALUES ($1, $2, $3, $4::jsonb)
        RETURNING id::text
        """,
        sanitize_text(filename),
        file_size,
        temp_path,
        json.dumps(sanitize_json(metadata or {}), ensure_ascii=False),
    )
    return row["id"]


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
    await conn.execute(
        """
        UPDATE public.document_ingest_jobs
        SET status = $2,
            progress = $3,
            doc_type = COALESCE($4, doc_type),
            text_length = COALESCE($5, text_length),
            chunk_count = COALESCE($6, chunk_count),
            embedding_batches = COALESCE($7, embedding_batches),
            document_id = COALESCE($8::uuid, document_id),
            error_code = $9,
            error_message = $10,
            stage_timings = stage_timings || $11::jsonb,
            updated_at = now()
        WHERE id = $1::uuid
        """,
        job_id,
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
    )


async def get_ingest_job(conn, *, job_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT id::text, status, progress, filename, doc_type, file_size, text_length,
               chunk_count, embedding_batches, document_id::text, error_code, error_message,
               stage_timings, metadata, created_at, updated_at
        FROM public.document_ingest_jobs
        WHERE id = $1::uuid
        """,
        job_id,
    )
    return dict(row) if row else None


async def fail_stale_ingest_jobs(conn) -> None:
    await conn.execute(
        """
        UPDATE public.document_ingest_jobs
        SET status = 'failed',
            progress = 100,
            error_code = 'JOB_INTERRUPTED',
            error_message = 'Document ingest job was interrupted by server restart.',
            updated_at = now()
        WHERE status IN ('pending', 'parsing', 'chunking', 'embedding', 'inserting')
        """
    )

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.lib.ai.embedding.service import EmbeddingUnavailableError, get_embedding_service
from app.lib.db.errors import is_missing_schema_error
from app.lib.db.pool import fetch_optional_pool
from app.lib.db.repositories.document import (
    delete_document,
    get_document,
    insert_chunks,
    insert_document,
    list_document_chunks,
    list_documents,
)
from app.lib.db.repositories.document_job import create_ingest_job, get_ingest_job, update_ingest_job
from app.lib.documents import DocumentParseError, parse_uploaded_document
from app.lib.documents.chunker import chunk_text
from app.lib.documents.parser import SUPPORTED_EXTENSIONS, TEXT_EXTENSIONS
from app.lib.documents.task_registry import schedule_task
from app.lib.ai.rag.mmr import mmr_select
from app.lib.ai.rerank import get_rerank_service
from app.lib.db.repositories.vector_search import search_hybrid_rrf
from app.shared.logging import log_event
from app.shared.settings import get_settings

router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 100


class DocumentCreateRequest(BaseModel):
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_url: str | None = None
    doc_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentCreateResponse(BaseModel):
    document_id: str
    chunk_count: int


class DocumentUploadJobResponse(BaseModel):
    job_id: str
    status: str


class DocumentListItem(BaseModel):
    id: str
    title: str
    source_url: str | None = None
    doc_type: str | None = None
    metadata: dict[str, Any] | None = None
    chunk_count: int
    latest_job_id: str | None = None
    latest_job_status: str | None = None
    created_at: str
    updated_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentListItem]


class DocumentDeleteResponse(BaseModel):
    deleted: bool


class DocumentJobResponse(BaseModel):
    id: str
    status: str
    progress: int
    filename: str | None = None
    doc_type: str | None = None
    file_size: int | None = None
    text_length: int | None = None
    chunk_count: int | None = None
    embedding_batches: int | None = None
    document_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    stage_timings: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_at: str
    updated_at: str


class DocumentDetailResponse(DocumentListItem):
    content_preview: str


class DocumentChunkItem(BaseModel):
    id: str
    document_id: str
    chunk_index: int
    content: str
    char_count: int
    token_count: int | None = None
    metadata: dict[str, Any] | None = None
    created_at: str


class DocumentChunksResponse(BaseModel):
    chunks: list[DocumentChunkItem]


class DocumentSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=8, ge=1, le=30)


class DocumentSearchResult(BaseModel):
    id: str
    document_id: str
    content_preview: str
    vector_score: float | None = None
    text_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    selected_by_mmr: bool = False


class DocumentSearchResponse(BaseModel):
    results: list[DocumentSearchResult]
    trace: dict[str, Any]


@router.get("/documents", response_model=DocumentListResponse)
async def list_knowledge_documents() -> DocumentListResponse:
    pool = await _require_document_db()
    async with pool.acquire() as conn:
        rows = await list_documents(conn)

    return DocumentListResponse(
        documents=[
            DocumentListItem(
                id=row["id"],
                title=row["title"],
                source_url=row["source_url"],
                doc_type=row["doc_type"],
                metadata=_metadata_dict(row["metadata"]),
                chunk_count=row["chunk_count"],
                latest_job_id=row.get("latest_job_id"),
                latest_job_status=row.get("latest_job_status"),
                created_at=_iso_datetime(row["created_at"]),
                updated_at=_iso_datetime(row["updated_at"]),
            )
            for row in rows
        ]
    )


@router.post("/documents", response_model=DocumentCreateResponse)
async def create_document(request: DocumentCreateRequest) -> DocumentCreateResponse:
    return await _store_document_content(
        title=request.title,
        content=request.content,
        doc_type=request.doc_type or "text",
        source_url=request.source_url,
        metadata=request.metadata,
    )


@router.post("/documents/upload", response_model=DocumentUploadJobResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str | None = Form(default=None),
    metadata: str | None = Form(default=None),
) -> DocumentUploadJobResponse:
    settings = get_settings()
    data = await file.read()
    if len(data) > settings.document_max_file_bytes:
        raise HTTPException(
            status_code=413,
            detail={"code": "FILE_TOO_LARGE", "message": "File exceeds the configured size limit."},
        )
    filename = file.filename or "document"
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "UNSUPPORTED_DOCUMENT_TYPE",
                "message": "Only txt, md, markdown, pdf, and docx files are supported.",
            },
        )
    parsed_metadata = _parse_form_metadata(metadata)
    if extension in TEXT_EXTENSIONS:
        try:
            parse_uploaded_document(
                filename=filename,
                content_type=file.content_type,
                data=data,
                title=title,
                settings=settings,
            )
        except DocumentParseError as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
    pool = await _require_document_db()
    upload_dir = Path(settings.storage_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_path = upload_dir / f"{uuid.uuid4().hex}{extension}"
    temp_path.write_bytes(data)
    try:
        async with pool.acquire() as conn:
            job_id = await create_ingest_job(
                conn,
                filename=filename,
                file_size=len(data),
                temp_path=str(temp_path),
                metadata={"title": title, "content_type": file.content_type, **parsed_metadata},
            )
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        if is_missing_schema_error(exc):
            raise _migration_required() from exc
        raise
    schedule_task(
        _run_document_ingest_job(
            job_id=job_id,
            temp_path=temp_path,
            filename=filename,
            content_type=file.content_type,
            title=title,
            metadata=parsed_metadata,
        )
    )
    return DocumentUploadJobResponse(job_id=job_id, status="pending")


@router.get("/documents/jobs/{job_id}", response_model=DocumentJobResponse)
async def get_document_job(job_id: str) -> DocumentJobResponse:
    pool = await _require_document_db()
    try:
        async with pool.acquire() as conn:
            row = await get_ingest_job(conn, job_id=job_id)
    except Exception as exc:
        if is_missing_schema_error(exc):
            raise _migration_required() from exc
        raise
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_JOB_NOT_FOUND", "message": "Document ingest job was not found."},
        )
    return _job_response(row)


@router.get("/documents/{document_id}", response_model=DocumentDetailResponse)
async def get_knowledge_document(document_id: str) -> DocumentDetailResponse:
    pool = await _require_document_db()
    async with pool.acquire() as conn:
        row = await get_document(conn, document_id=document_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": "Document was not found."},
        )
    content = str(row["content"] or "")
    return DocumentDetailResponse(
        id=row["id"],
        title=row["title"],
        source_url=row["source_url"],
        doc_type=row["doc_type"],
        metadata=_metadata_dict(row["metadata"]),
        chunk_count=row["chunk_count"],
        created_at=_iso_datetime(row["created_at"]),
        updated_at=_iso_datetime(row["updated_at"]),
        content_preview=content[:1200],
    )


@router.get("/documents/{document_id}/chunks", response_model=DocumentChunksResponse)
async def get_knowledge_document_chunks(
    document_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> DocumentChunksResponse:
    pool = await _require_document_db()
    async with pool.acquire() as conn:
        rows = await list_document_chunks(conn, document_id=document_id, limit=limit, offset=offset)
    return DocumentChunksResponse(
        chunks=[
            DocumentChunkItem(
                id=row["id"],
                document_id=row["document_id"],
                chunk_index=row["chunk_index"],
                content=row["content"],
                char_count=len(row["content"] or ""),
                token_count=row["token_count"],
                metadata=_metadata_dict(row["metadata"]),
                created_at=_iso_datetime(row["created_at"]),
            )
            for row in rows
        ]
    )


@router.post("/documents/search", response_model=DocumentSearchResponse)
async def search_knowledge_documents(request: DocumentSearchRequest) -> DocumentSearchResponse:
    settings = get_settings()
    pool = await _require_document_db()
    started = time.perf_counter()
    embedding = await get_embedding_service().embed_text(request.query)
    embedding_ms = int((time.perf_counter() - started) * 1000)
    async with pool.acquire() as conn:
        recall_started = time.perf_counter()
        candidates = await search_hybrid_rrf(
            conn,
            embedding=embedding,
            query=request.query,
            limit=max(settings.rag_candidate_limit, request.limit),
            k=settings.rag_rrf_k,
        )
    recall_ms = int((time.perf_counter() - recall_started) * 1000)
    rerank_started = time.perf_counter()
    ranked = await get_rerank_service().rerank(
        query=request.query,
        items=candidates,
        top_n=min(len(candidates), request.limit + 3),
    )
    rerank_ms = int((time.perf_counter() - rerank_started) * 1000)
    selected = (
        mmr_select(
            candidates=ranked,
            query_embedding=embedding,
            top_n=request.limit,
            lambda_mult=settings.rag_mmr_lambda,
        )
        if settings.rag_mmr_enabled
        else ranked[: request.limit]
    )
    selected_ids = {item["id"] for item in selected}
    return DocumentSearchResponse(
        results=[
            DocumentSearchResult(
                id=item["id"],
                document_id=item["document_id"],
                content_preview=str(item.get("content") or "")[:500],
                vector_score=_optional_float(item.get("vector_score")),
                text_score=_optional_float(item.get("text_score")),
                rrf_score=_optional_float(item.get("rrf_score")),
                rerank_score=_optional_float(item.get("rerank_score")),
                selected_by_mmr=item["id"] in selected_ids,
            )
            for item in selected
        ],
        trace={
            "query_chars": len(request.query),
            "embedding_ms": embedding_ms,
            "candidates": len(candidates),
            "recall_ms": recall_ms,
            "rerank_ms": rerank_ms,
            "mmr_selected": len(selected),
        },
    )


async def _store_document_content(
    *,
    title: str,
    content: str,
    doc_type: str,
    source_url: str | None,
    metadata: dict[str, Any],
    job_id: str | None = None,
) -> DocumentCreateResponse:
    settings = get_settings()
    stage_timings: dict[str, int] = {}
    started = time.perf_counter()
    chunks = chunk_text(
        content,
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        min_chunk_size=settings.chunk_min_size,
    )
    stage_timings["chunking_ms"] = int((time.perf_counter() - started) * 1000)
    if len(chunks) > settings.document_max_chunks:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "DOCUMENT_TOO_MANY_CHUNKS",
                "message": "Document exceeds the configured chunk limit.",
            },
        )

    pool = await _require_document_db()
    if job_id:
        async with pool.acquire() as conn:
            await update_ingest_job(
                conn,
                job_id=job_id,
                status="embedding",
                progress=55,
                chunk_count=len(chunks),
                embedding_batches=(len(chunks) + settings.embedding_batch_size - 1)
                // settings.embedding_batch_size,
                stage_timings=stage_timings,
            )
    log_event(
        logger,
        "documents.chunk",
        document_id="pending",
        chunk_count=len(chunks),
        chunk_size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )

    try:
        started = time.perf_counter()
        embeddings = await get_embedding_service().embed_batch(chunks)
        stage_timings["embedding_ms"] = int((time.perf_counter() - started) * 1000)
    except EmbeddingUnavailableError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "EMBEDDING_UNAVAILABLE", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.exception("Document embedding request failed.")
        raise HTTPException(
            status_code=500,
            detail={"code": "EMBEDDING_UNAVAILABLE", "message": "Embedding request failed."},
        ) from exc

    if job_id:
        async with pool.acquire() as conn:
            await update_ingest_job(
                conn,
                job_id=job_id,
                status="inserting",
                progress=80,
                stage_timings=stage_timings,
            )
    started = time.perf_counter()
    async with pool.acquire() as conn:
        async with conn.transaction():
            document_id = await insert_document(
                conn,
                title=title,
                content=content,
                source_url=source_url,
                doc_type=doc_type,
                metadata=metadata,
            )
            chunk_metadata = dict(metadata)
            if source_url:
                chunk_metadata["source_url"] = source_url
            await insert_chunks(
                conn,
                document_id=document_id,
                chunks=[
                    (
                        index,
                        content,
                        embedding,
                        None,
                        chunk_metadata,
                    )
                    for index, (content, embedding) in enumerate(zip(chunks, embeddings, strict=True))
                ],
            )
    stage_timings["inserting_ms"] = int((time.perf_counter() - started) * 1000)
    if job_id:
        async with pool.acquire() as conn:
            await update_ingest_job(
                conn,
                job_id=job_id,
                status="complete",
                progress=100,
                document_id=document_id,
                chunk_count=len(chunks),
                embedding_batches=(len(chunks) + settings.embedding_batch_size - 1)
                // settings.embedding_batch_size,
                stage_timings=stage_timings,
            )
    log_event(
        logger,
        "documents.insert",
        document_id=document_id,
        chunks_inserted=len(chunks),
    )

    return DocumentCreateResponse(document_id=document_id, chunk_count=len(chunks))


async def _run_document_ingest_job(
    *,
    job_id: str,
    temp_path: Path,
    filename: str,
    content_type: str | None,
    title: str | None,
    metadata: dict[str, Any],
) -> None:
    settings = get_settings()
    stage_timings: dict[str, int] = {}
    try:
        pool = await _require_document_db()
        async with pool.acquire() as conn:
            await update_ingest_job(conn, job_id=job_id, status="parsing", progress=15)
        started = time.perf_counter()
        data = temp_path.read_bytes()
        parsed = parse_uploaded_document(
            filename=filename,
            content_type=content_type,
            data=data,
            title=title,
            settings=settings,
        )
        stage_timings["parsing_ms"] = int((time.perf_counter() - started) * 1000)
        async with pool.acquire() as conn:
            await update_ingest_job(
                conn,
                job_id=job_id,
                status="chunking",
                progress=35,
                doc_type=parsed.doc_type,
                text_length=len(parsed.content),
                stage_timings=stage_timings,
            )
        log_event(
            logger,
            "documents.upload",
            filename=parsed.metadata.get("filename"),
            doc_type=parsed.doc_type,
            file_size=parsed.metadata.get("file_size"),
            page_count=parsed.metadata.get("page_count", 0),
            text_length=parsed.metadata.get("text_length", len(parsed.content)),
        )
        await _store_document_content(
            title=parsed.title,
            content=parsed.content,
            doc_type=parsed.doc_type,
            source_url=None,
            metadata={**parsed.metadata, **metadata},
            job_id=job_id,
        )
    except DocumentParseError as exc:
        await _fail_ingest_job(job_id, exc.code, exc.message)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        await _fail_ingest_job(
            job_id,
            str(detail.get("code") or "DOCUMENT_INGEST_FAILED"),
            str(detail.get("message") or exc.detail),
        )
    except Exception as exc:
        logger.exception("Document ingest job failed.")
        await _fail_ingest_job(job_id, "DOCUMENT_INGEST_FAILED", str(exc))
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to remove upload temp file: %s", temp_path)


async def _fail_ingest_job(job_id: str, code: str, message: str) -> None:
    pool = await fetch_optional_pool()
    if pool is None:
        return
    async with pool.acquire() as conn:
        await update_ingest_job(
            conn,
            job_id=job_id,
            status="failed",
            progress=100,
            error_code=code,
            error_message=message,
        )


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse)
async def remove_document(document_id: str) -> DocumentDeleteResponse:
    pool = await _require_document_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            deleted = await delete_document(conn, document_id=document_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "DOCUMENT_NOT_FOUND", "message": "Document was not found."},
        )
    return DocumentDeleteResponse(deleted=True)


async def _require_document_db():
    settings = get_settings()
    if not settings.database_enabled:
        raise HTTPException(
            status_code=503,
            detail={"code": "DATABASE_DISABLED", "message": "Database is not enabled."},
        )
    pool = await fetch_optional_pool()
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "DATABASE_UNAVAILABLE", "message": "Database is unavailable."},
        )
    return pool


def _metadata_dict(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {"raw": value}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {"value": value}


def _parse_form_metadata(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_METADATA", "message": "metadata must be valid JSON."},
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_METADATA", "message": "metadata must be a JSON object."},
        )
    return parsed


def _iso_datetime(value: Any) -> str:
    if value is None:
        return ""
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _job_response(row: dict[str, Any]) -> DocumentJobResponse:
    return DocumentJobResponse(
        id=row["id"],
        status=row["status"],
        progress=row["progress"],
        filename=row["filename"],
        doc_type=row["doc_type"],
        file_size=row["file_size"],
        text_length=row["text_length"],
        chunk_count=row["chunk_count"],
        embedding_batches=row["embedding_batches"],
        document_id=row["document_id"],
        error_code=row["error_code"],
        error_message=row["error_message"],
        stage_timings=_metadata_dict(row["stage_timings"]),
        metadata=_metadata_dict(row["metadata"]),
        created_at=_iso_datetime(row["created_at"]),
        updated_at=_iso_datetime(row["updated_at"]),
    )


def _optional_float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _migration_required() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "DATABASE_MIGRATION_REQUIRED",
            "message": "Database schema is not up to date. Run backend/sql/apply.py and restart the backend.",
        },
    )


def split_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    return chunk_text(text, chunk_size=chunk_size, chunk_overlap=overlap)

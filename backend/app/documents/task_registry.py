from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from app.db.errors import is_missing_schema_error
from app.db.pool import fetch_optional_pool
from app.db.repositories.document_job import fail_stale_ingest_jobs
from app.core.settings import get_settings

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()


def schedule_task(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def shutdown_tasks(timeout_seconds: float = 5) -> None:
    if not _tasks:
        return
    try:
        await asyncio.wait_for(asyncio.gather(*_tasks, return_exceptions=True), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning("Document ingest tasks did not finish before shutdown.")


async def recover_document_jobs() -> None:
    pool = await fetch_optional_pool()
    stale_paths: list[str] = []
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                stale_paths = await fail_stale_ingest_jobs(conn)
        except Exception as exc:
            if is_missing_schema_error(exc):
                logger.warning(
                    "Document ingest job table is missing. Run backend/sql/apply.py to enable upload jobs."
                )
            else:
                logger.exception("Failed to mark stale document ingest jobs.")
    cleanup_stale_job_uploads(stale_paths)
    cleanup_orphan_uploads()


def cleanup_stale_job_uploads(temp_paths: list[str]) -> int:
    """Remove only files that resolve directly inside the configured upload root."""

    upload_root = Path(get_settings().storage_upload_dir).resolve()
    removed = 0
    for value in temp_paths:
        candidate = Path(value)
        try:
            resolved = candidate.resolve(strict=False)
            if resolved.parent != upload_root:
                logger.warning("Refused stale upload cleanup outside upload root: %s", candidate)
                continue
            existed = candidate.exists() or candidate.is_symlink()
            candidate.unlink(missing_ok=True)
            if existed:
                removed += 1
        except (OSError, RuntimeError, ValueError):
            logger.warning("Failed to clean stale document upload: %s", candidate, exc_info=True)
    if removed:
        logger.info("Removed %d stale document upload file(s).", removed)
    return removed


def cleanup_orphan_uploads() -> None:
    settings = get_settings()
    upload_dir = Path(settings.storage_upload_dir)
    if not upload_dir.exists():
        return
    max_age = settings.storage_orphan_max_age_hours * 3600
    now = time.time()
    for path in upload_dir.glob("*"):
        if not path.is_file():
            continue
        try:
            if now - path.stat().st_mtime > max_age:
                path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Failed to clean orphan upload file: %s", path)

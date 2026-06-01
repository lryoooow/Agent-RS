from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from app.lib.db.errors import is_missing_schema_error
from app.lib.db.pool import fetch_optional_pool
from app.lib.db.repositories.document_job import fail_stale_ingest_jobs
from app.shared.settings import get_settings

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
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                await fail_stale_ingest_jobs(conn)
        except Exception as exc:
            if is_missing_schema_error(exc):
                logger.warning(
                    "Document ingest job table is missing. Run backend/sql/apply.py to enable upload jobs."
                )
            else:
                logger.exception("Failed to mark stale document ingest jobs.")
    cleanup_orphan_uploads()


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

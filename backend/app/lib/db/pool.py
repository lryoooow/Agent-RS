from __future__ import annotations

import logging
from typing import Any

from app.shared.settings import get_settings

logger = logging.getLogger(__name__)

_pool: Any | None = None


async def init_db_pool() -> None:
    global _pool
    settings = get_settings()
    if not settings.database_enabled:
        _pool = None
        return
    if not settings.database_url:
        logger.warning("DATABASE_ENABLED=true but DATABASE_URL is empty; database disabled.")
        _pool = None
        return
    if _pool is not None:
        return

    try:
        import asyncpg
    except ImportError:
        logger.warning("asyncpg is not installed; database disabled.")
        _pool = None
        return

    try:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=settings.database_pool_min_size,
            max_size=settings.database_pool_max_size,
        )
    except Exception:
        logger.exception("Failed to initialize database pool; database disabled.")
        _pool = None


async def close_db_pool() -> None:
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None


async def get_db_pool() -> Any | None:
    if _pool is None:
        await init_db_pool()
    return _pool


async def fetch_optional_pool() -> Any | None:
    try:
        return await get_db_pool()
    except Exception:
        logger.exception("Failed to fetch database pool.")
        return None

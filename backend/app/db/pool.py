from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_pool: Any | None = None
_pool_initialized = False
# A single process owns one asyncpg pool. The lock covers both initialization and
# shutdown so concurrent first requests cannot create orphan pools and shutdown
# cannot close a pool while another coroutine is still publishing it.
_pool_state_lock = asyncio.Lock()


async def init_db_pool() -> None:
    async with _pool_state_lock:
        await _init_db_pool_locked()


async def _init_db_pool_locked() -> None:
    global _pool, _pool_initialized
    settings = get_settings()

    if not settings.database_enabled:
        _pool = None
        _pool_initialized = True
        return
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_ENABLED=true 但 DATABASE_URL 为空；"
            "请配置数据库连接串或显式设 DATABASE_ENABLED=false。"
        )
    if _pool is not None or _pool_initialized:
        return

    try:
        import asyncpg
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_ENABLED=true 但未安装 asyncpg；请安装依赖或关闭数据库。"
        ) from exc

    try:
        _pool = await asyncpg.create_pool(
            dsn=settings.database_url,
            min_size=settings.database_pool_min_size,
            max_size=settings.database_pool_max_size,
        )
    except Exception as exc:
        _pool = None
        _pool_initialized = False
        database_target = settings.database_url.rsplit("@", 1)[-1]
        raise RuntimeError(
            f"无法连接数据库（{database_target}）。"
            "请先启动数据库：`docker compose up -d db`，"
            f"或设 DATABASE_ENABLED=false。原始错误：{exc}"
        ) from exc

    try:
        # Startup schema application is part of pool readiness. Publishing a pool
        # with a partially applied schema only moves the failure into user traffic.
        await _ensure_schema()
    except Exception as exc:
        logger.exception("Schema migration on startup failed.")
        created_pool = _pool
        _pool = None
        _pool_initialized = False
        if created_pool is not None:
            await created_pool.close()
        raise RuntimeError(
            "数据库 schema 迁移失败，连接池未启用；请检查迁移日志后重试。"
        ) from exc

    _pool_initialized = True


async def _ensure_schema() -> None:
    if _pool is None:
        return
    from sql.apply import run_migrations

    async with _pool.acquire() as conn:
        applied = await run_migrations(conn, log=None)
    if applied:
        logger.info(
            "Applied %d database migration(s): %s",
            len(applied),
            ", ".join(applied),
        )


async def close_db_pool() -> None:
    global _pool, _pool_initialized
    async with _pool_state_lock:
        pool = _pool
        _pool = None
        _pool_initialized = False
        if pool is not None:
            await pool.close()


async def get_db_pool() -> Any | None:
    if _pool is None and not _pool_initialized:
        await init_db_pool()
    return _pool


async def fetch_optional_pool() -> Any | None:
    try:
        return await get_db_pool()
    except Exception:
        logger.exception("Failed to fetch database pool.")
        return None

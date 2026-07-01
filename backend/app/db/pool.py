from __future__ import annotations

import logging
from typing import Any

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_pool: Any | None = None
_pool_initialized = False


async def init_db_pool() -> None:
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
    if _pool is not None:
        return
    if _pool_initialized:
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
        _pool_initialized = True
    except Exception as exc:
        _pool = None
        _pool_initialized = False
        database_target = settings.database_url.rsplit("@", 1)[-1]
        raise RuntimeError(
            f"无法连接数据库（{database_target}）。"
            "请先启动数据库：`docker compose up -d db`，"
            f"或设 DATABASE_ENABLED=false。原始错误：{exc}"
        ) from exc

    # 启动时幂等建/补 schema：docker compose up + 启动后端即自带最新表结构，免手动 sql.apply。
    # 已按 schema_migrations 记录跳过已应用版本，重复启动零副作用；失败只告警，不阻断启动
    # （库刚拉起尚未就绪等场景，由后续请求经 fetch_optional_pool 容错）。
    await _ensure_schema()


async def _ensure_schema() -> None:
    if _pool is None:
        return
    try:
        from sql.apply import run_migrations

        async with _pool.acquire() as conn:
            applied = await run_migrations(conn, log=None)
        if applied:
            logger.info("Applied %d database migration(s): %s", len(applied), ", ".join(applied))
    except Exception:
        logger.exception("Schema migration on startup failed; run `python -m sql.apply` manually.")


async def close_db_pool() -> None:
    global _pool, _pool_initialized
    if _pool is None:
        _pool_initialized = False
        return
    await _pool.close()
    _pool = None
    _pool_initialized = False


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

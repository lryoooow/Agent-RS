from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.pool import close_db_pool, get_db_pool, init_db_pool

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{4})_.+\.sql$")
_MIGRATION_LOCK_SQL = "SELECT pg_advisory_lock(hashtext('agent-rs-schema-migrations'))"
_MIGRATION_UNLOCK_SQL = "SELECT pg_advisory_unlock(hashtext('agent-rs-schema-migrations'))"


def migration_paths(directory: Path = MIGRATIONS_DIR) -> list[Path]:
    """Return a complete, uniquely numbered migration sequence.

    A skipped or duplicate number is treated as a packaging error before any SQL
    is executed. Reserved numbers must therefore have an explicit no-op migration,
    making an intentional gap auditable instead of indistinguishable from loss.
    """
    paths = sorted(directory.glob("*.sql"))
    if not paths:
        raise RuntimeError(f"没有找到数据库迁移文件：{directory}")

    numbers: list[int] = []
    for path in paths:
        match = _MIGRATION_NAME.fullmatch(path.name)
        if match is None:
            raise RuntimeError(f"迁移文件名不符合 NNNN_name.sql 约定：{path.name}")
        numbers.append(int(match.group(1)))
    if len(numbers) != len(set(numbers)):
        raise RuntimeError("数据库迁移版本号重复。")
    expected = list(range(numbers[0], numbers[-1] + 1))
    if numbers != expected:
        missing = sorted(set(expected) - set(numbers))
        rendered = ", ".join(f"{number:04d}" for number in missing)
        raise RuntimeError(f"数据库迁移版本不连续，缺少：{rendered}")
    return paths


async def run_migrations(conn, *, log=print) -> list[str]:
    """Apply all migrations once, serialized across concurrent app instances."""
    paths = migration_paths()
    await conn.execute(_MIGRATION_LOCK_SQL)
    try:
        return await _run_migrations_locked(conn, paths=paths, log=log)
    finally:
        await conn.execute(_MIGRATION_UNLOCK_SQL)


async def _run_migrations_locked(conn, *, paths: list[Path], log=print) -> list[str]:
    # Compatibility path for databases created before the Agent-RS rename.
    old_exists = await conn.fetchval(
        "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'chatbot'"
    )
    new_exists = await conn.fetchval(
        "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'agent_rs'"
    )
    if old_exists and not new_exists:
        await conn.execute("ALTER SCHEMA chatbot RENAME TO agent_rs")
    await conn.execute("CREATE SCHEMA IF NOT EXISTS agent_rs")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_rs.schema_migrations (
          version TEXT PRIMARY KEY,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    rows = await conn.fetch("SELECT version FROM agent_rs.schema_migrations")
    applied = {row["version"] for row in rows}

    newly_applied: list[str] = []
    for path in paths:
        version = path.stem
        if version in applied:
            continue
        async with conn.transaction():
            await conn.execute(path.read_text(encoding="utf-8"))
            await conn.execute(
                "INSERT INTO agent_rs.schema_migrations (version) VALUES ($1)",
                version,
            )
        newly_applied.append(version)
        if log is not None:
            log(f"applied {version}")
    return newly_applied


async def apply_migrations() -> None:
    await init_db_pool()
    pool = await get_db_pool()
    if pool is None:
        raise RuntimeError("Database is disabled or DATABASE_URL is not configured.")

    async with pool.acquire() as conn:
        await run_migrations(conn)

    await close_db_pool()


def main() -> None:
    asyncio.run(apply_migrations())


if __name__ == "__main__":
    main()

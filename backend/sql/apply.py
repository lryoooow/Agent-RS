from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.pool import close_db_pool, get_db_pool, init_db_pool

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


async def run_migrations(conn, *, log=print) -> list[str]:
    """在已有连接上幂等应用所有 migration，返回本次新应用的版本号列表。

    抽出为独立函数：既供 CLI（apply_migrations）调用，也供启动时 init_db_pool 复用，
    避免后者再开关一次连接池。已记录到 schema_migrations 的版本跳过，重复调用零副作用。
    """
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
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
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

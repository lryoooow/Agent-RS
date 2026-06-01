from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.lib.db.pool import close_db_pool, get_db_pool, init_db_pool

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


async def apply_migrations() -> None:
    await init_db_pool()
    pool = await get_db_pool()
    if pool is None:
        raise RuntimeError("Database is disabled or DATABASE_URL is not configured.")

    async with pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS chatbot")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS chatbot.schema_migrations (
              version TEXT PRIMARY KEY,
              applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        rows = await conn.fetch("SELECT version FROM chatbot.schema_migrations")
        applied = {row["version"] for row in rows}

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            if version in applied:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute(
                    "INSERT INTO chatbot.schema_migrations (version) VALUES ($1)",
                    version,
                )
            print(f"applied {version}")

    await close_db_pool()


def main() -> None:
    asyncio.run(apply_migrations())


if __name__ == "__main__":
    main()

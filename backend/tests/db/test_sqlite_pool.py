from __future__ import annotations

import pytest

from app.db.sqlite_pool import _qmark, create_sqlite_pool


@pytest.fixture
async def pool(tmp_path):
    db_path = str(tmp_path / "test.db")
    return await create_sqlite_pool(db_path)


def test_qmark_translates_dollar_placeholders():
    assert _qmark("SELECT * FROM t WHERE id = $1 AND x = $2") == "SELECT * FROM t WHERE id = ? AND x = ?"
    assert _qmark("no placeholders") == "no placeholders"
    # $10 etc. fully consumed (multi-digit)
    assert _qmark("a $1 b $10 c") == "a ? b ? c"


async def test_schema_applied_tables_exist(pool):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT name FROM sqlite_master WHERE type='table'")
        names = {row["name"] for row in rows}
    for expected in (
        "users", "workspaces", "memberships", "conversations", "messages",
        "sessions", "documents", "document_chunks", "memories",
        "document_ingest_jobs", "embedding_retry", "document_chunks_fts",
    ):
        assert expected in names, f"missing table {expected}"


async def test_fetch_fetchrow_fetchval_execute(pool):
    async with pool.acquire() as conn:
        n = await conn.execute(
            "INSERT INTO users (id, email, name) VALUES (?, ?, ?)",
            "u1", "a@b.c", "Alice",
        )
        assert n == 1  # rowcount, not a PG command-tag string

        row = await conn.fetchrow("SELECT id, email, name FROM users WHERE id = ?", "u1")
        assert dict(row) == {"id": "u1", "email": "a@b.c", "name": "Alice"}  # row_factory=Row

        rows = await conn.fetch("SELECT id FROM users")
        assert [r["id"] for r in rows] == ["u1"]

        val = await conn.fetchval("SELECT count(*) FROM users")
        assert val == 1

        missing = await conn.fetchrow("SELECT id FROM users WHERE id = ?", "nope")
        assert missing is None


async def test_dollar_placeholder_executes(pool):
    # Safety net: a stray $N placeholder still runs correctly.
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO users (id, email) VALUES ($1, $2)", "u2", "x@y.z")
        val = await conn.fetchval("SELECT email FROM users WHERE id = $1", "u2")
        assert val == "x@y.z"


async def test_transaction_commit(pool):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("INSERT INTO users (id, email) VALUES (?, ?)", "tc", "t@c.c")
        val = await conn.fetchval("SELECT count(*) FROM users WHERE id = ?", "tc")
        assert val == 1


async def test_transaction_rollback_on_error(pool):
    async with pool.acquire() as conn:
        with pytest.raises(RuntimeError):
            async with conn.transaction():
                await conn.execute("INSERT INTO users (id, email) VALUES (?, ?)", "rb", "r@b.c")
                raise RuntimeError("boom")
        val = await conn.fetchval("SELECT count(*) FROM users WHERE id = ?", "rb")
        assert val == 0  # rolled back


async def test_foreign_keys_enforced(pool):
    # PRAGMA foreign_keys=ON per connection: orphan FK insert must fail.
    import sqlite3

    async with pool.acquire() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            await conn.execute(
                "INSERT INTO sessions (id, user_id, token_hash, expires_at) VALUES (?, ?, ?, ?)",
                "s1", "ghost-user", "hash", "2099-01-01 00:00:00",
            )


async def test_fts_trigger_syncs_on_insert(pool):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO documents (id, title, content) VALUES (?, ?, ?)",
            "d1", "t", "body",
        )
        await conn.execute(
            "INSERT INTO document_chunks (id, document_id, chunk_index, content) VALUES (?, ?, ?, ?)",
            "c1", "d1", 0, "the quick brown fox",
        )
        rows = await conn.fetch(
            "SELECT c.id FROM document_chunks_fts f "
            "JOIN document_chunks c ON c.rowid = f.rowid "
            "WHERE document_chunks_fts MATCH ?",
            "quick",
        )
        assert [r["id"] for r in rows] == ["c1"]

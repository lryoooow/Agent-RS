"""asyncpg 连接的通用语义测试（从 test_sqlite_pool.py 移植）。

只保留与后端无关的"连接接口契约"：fetch/fetchrow/fetchval/execute 的返回形态、
事务提交、外键约束真生效。SQLite 专属用例（_qmark 占位符转换、sqlite_master 建表自检、
FTS5 触发器同步、$N 在 SQLite 也能跑）随 SQLite 退役一并删除——PG 原生用 $N 占位符、
GENERATED tsvector 列做 FTS，不需要这些适配层。

事务回滚语义已在 test_pg_backend.py::test_transaction_rollback_on_error 覆盖，此处不重复。
"""
from __future__ import annotations

import asyncpg
import pytest

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_fetch_fetchrow_fetchval_execute(pg_conn) -> None:
    # 连接接口契约：execute 返回命令标签字符串（PG 风格，非 SQLite 的 rowcount 整数）；
    # fetchrow 取单行 / fetch 取多行 / fetchval 取标量 / 无命中 fetchrow → None。
    tag = await pg_conn.execute(
        "INSERT INTO agent_rs.users (id, email, name) VALUES ($1::uuid, $2, $3)",
        "00000000-0000-4000-8000-000000000a01", "a@b.c", "Alice",
    )
    assert tag == "INSERT 0 1"  # PG 命令标签，区别于 SQLite 适配器的 rowcount

    row = await pg_conn.fetchrow(
        "SELECT email, name FROM agent_rs.users WHERE id = $1::uuid",
        "00000000-0000-4000-8000-000000000a01",
    )
    assert dict(row) == {"email": "a@b.c", "name": "Alice"}

    rows = await pg_conn.fetch("SELECT email FROM agent_rs.users")
    assert [r["email"] for r in rows] == ["a@b.c"]

    val = await pg_conn.fetchval("SELECT count(*) FROM agent_rs.users")
    assert val == 1

    missing = await pg_conn.fetchrow(
        "SELECT id FROM agent_rs.users WHERE id = $1::uuid",
        "00000000-0000-4000-8000-0000000000ff",
    )
    assert missing is None


async def test_transaction_commit(pg_conn) -> None:
    # 事务正常提交后数据可见。
    async with pg_conn.transaction():
        await pg_conn.execute(
            "INSERT INTO agent_rs.users (id, email) VALUES ($1::uuid, $2)",
            "00000000-0000-4000-8000-000000000a02", "t@c.c",
        )
    val = await pg_conn.fetchval(
        "SELECT count(*) FROM agent_rs.users WHERE id = $1::uuid",
        "00000000-0000-4000-8000-000000000a02",
    )
    assert val == 1


async def test_foreign_keys_enforced(pg_conn) -> None:
    # 外键约束真生效：插入引用不存在用户的 session → ForeignKeyViolationError。
    # PG 原生强制外键（无需 SQLite 的 PRAGMA foreign_keys=ON）。
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await pg_conn.execute(
            "INSERT INTO agent_rs.sessions (id, user_id, token_hash, expires_at) "
            "VALUES ($1::uuid, $2::uuid, $3, now() + interval '1 day')",
            "00000000-0000-4000-8000-000000000a03",
            "00000000-0000-4000-8000-0000000000ff",  # 不存在的 user
            "hash",
        )

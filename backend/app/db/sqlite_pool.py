from __future__ import annotations

import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "sqlite_schema.sql"


def _qmark(sql: str) -> str:
    """把仓储里残留的 asyncpg `$1` 占位符转成 SQLite 的 `?`。

    `_sqlite/` 仓储本就写 `?`，此函数只是双保险：万一某条 SQL 漏改 `$N`，
    也能正确执行（按出现顺序替换，参数顺序与 asyncpg 一致）。
    """
    if "$" not in sql:
        return sql
    out: list[str] = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch == "$" and i + 1 < n and sql[i + 1].isdigit():
            i += 1
            while i < n and sql[i].isdigit():
                i += 1
            out.append("?")
            continue
        out.append(ch)
        i += 1
    return "".join(out)


class SQLiteConnection:
    """aiosqlite 连接的薄封装，复刻 asyncpg 连接接口：

    fetch / fetchrow / fetchval / execute(sql, *params) + transaction()。
    行以 dict-like（sqlite3.Row）返回，故仓储里的 `dict(row)` / `row["col"]` 不变。
    """

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def fetch(self, sql: str, *params: Any) -> list[sqlite3.Row]:
        cursor = await self._conn.execute(_qmark(sql), params)
        try:
            return list(await cursor.fetchall())
        finally:
            await cursor.close()

    async def fetchrow(self, sql: str, *params: Any) -> sqlite3.Row | None:
        cursor = await self._conn.execute(_qmark(sql), params)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def fetchval(self, sql: str, *params: Any) -> Any:
        row = await self.fetchrow(sql, *params)
        if row is None:
            return None
        return row[0]

    async def execute(self, sql: str, *params: Any) -> int:
        """执行写语句，返回受影响行数（rowcount）。

        与 asyncpg 返回命令标签字符串不同——`_sqlite/` 仓储据此用
        `rowcount == 1` 判定，绝不沿用 PG 的 `result.endswith(" 1")`。
        """
        cursor = await self._conn.execute(_qmark(sql), params)
        try:
            return cursor.rowcount
        finally:
            await cursor.close()

    @asynccontextmanager
    async def transaction(self):
        """显式事务。连接处于 autocommit(isolation_level=None)，

        故这里手动 BEGIN/COMMIT/ROLLBACK，避免 sqlite3 自动事务与
        手动 BEGIN 撞车（"cannot start a transaction within a transaction"）。
        无嵌套/savepoint 使用，单层即可。
        """
        await self._conn.execute("BEGIN")
        try:
            yield self
        except BaseException:
            await self._conn.execute("ROLLBACK")
            raise
        else:
            await self._conn.execute("COMMIT")


class SQLitePool:
    """复刻 asyncpg 连接池接口：`async with pool.acquire() as conn:` + close()。

    采用"每次 acquire 开一条新连接"：SQLite 单连接不宜在并发任务间交错事务，
    而 request_builder 会用 asyncio.gather 同时 acquire 两次。每条连接独立、
    用完即关，写入靠 SQLite 文件锁 + busy_timeout 串行化，简单可靠。
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    @asynccontextmanager
    async def acquire(self):
        # isolation_level=None (autocommit) 必须在 connect 时传入：aiosqlite 把真实
        # sqlite3 连接放在专属线程，事后用属性 setter 设 isolation_level 会跨线程报错。
        conn = await aiosqlite.connect(self._db_path, isolation_level=None)
        try:
            conn.row_factory = sqlite3.Row  # dict(row)/row["col"] 依赖此项
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA busy_timeout=5000")
            await conn.execute("PRAGMA journal_mode=WAL")
            yield SQLiteConnection(conn)
        finally:
            await conn.close()

    async def close(self) -> None:
        # 无持久连接需要释放（每 acquire 独立开关），此处为接口对齐 asyncpg。
        return None


async def create_sqlite_pool(db_path: str) -> SQLitePool:
    """建库目录、建表（executescript 幂等），返回池。"""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(schema_sql)
        await conn.commit()
    logger.info("SQLite storage initialized at %s", db_path)
    return SQLitePool(db_path)

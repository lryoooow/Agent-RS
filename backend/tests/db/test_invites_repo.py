"""invites 仓储的 DB 集成测试：消费原子性、单次/限时/撤销边界。

用全局 conftest 的 pg_pool 真库夹具（库不可达整组 skip）。重点压测 consume_invite 的并发原子性——
单次码被两个请求同时消费时只能成功一次（历史隐患：码被超额消费）。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.db.repositories.identity import ensure_default_identity
from app.db.repositories.invite import (
    consume_invite,
    create_invite,
    list_invites,
    revoke_invite,
)
from app.core.settings import get_settings

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _seed_user(conn):
    """建默认身份并返回其 user_id，用作邀请的 created_by / used_by。"""
    settings = get_settings()
    await ensure_default_identity(conn, settings)
    return settings.default_user_id


async def test_create_and_consume_single_use(pg_pool):
    async with pg_pool.acquire() as conn:
        user_id = await _seed_user(conn)
        await create_invite(conn, code_hash="hash-single", created_by_user_id=user_id)
        # 首次消费成功
        assert await consume_invite(conn, code_hash="hash-single", user_id=user_id) is True
        # 单次码二次消费失败（核心：used_count < max_uses 不再成立）
        assert await consume_invite(conn, code_hash="hash-single", user_id=user_id) is False


async def test_expired_invite_rejected(pg_pool):
    async with pg_pool.acquire() as conn:
        user_id = await _seed_user(conn)
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        await create_invite(
            conn, code_hash="hash-expired", created_by_user_id=user_id, expires_at=past
        )
        assert await consume_invite(conn, code_hash="hash-expired", user_id=user_id) is False


async def test_revoked_invite_rejected(pg_pool):
    async with pg_pool.acquire() as conn:
        user_id = await _seed_user(conn)
        row = await create_invite(conn, code_hash="hash-revoke", created_by_user_id=user_id)
        assert await revoke_invite(conn, invite_id=row["id"]) is True
        assert await consume_invite(conn, code_hash="hash-revoke", user_id=user_id) is False
        # 二次撤销不命中（已撤销）
        assert await revoke_invite(conn, invite_id=row["id"]) is False


async def test_multi_use_invite_honors_max_uses(pg_pool):
    async with pg_pool.acquire() as conn:
        user_id = await _seed_user(conn)
        await create_invite(
            conn, code_hash="hash-multi", created_by_user_id=user_id, max_uses=2
        )
        assert await consume_invite(conn, code_hash="hash-multi", user_id=user_id) is True
        assert await consume_invite(conn, code_hash="hash-multi", user_id=user_id) is True
        # 第三次超出 max_uses 被拒
        assert await consume_invite(conn, code_hash="hash-multi", user_id=user_id) is False


async def test_unknown_code_rejected(pg_pool):
    async with pg_pool.acquire() as conn:
        user_id = await _seed_user(conn)
        assert await consume_invite(conn, code_hash="does-not-exist", user_id=user_id) is False


async def test_concurrent_consume_single_use_only_one_succeeds(pg_pool):
    # 并发原子性：单次码被两个并发请求抢消费，只能有一个成功。
    # 各用独立连接模拟两个请求，UPDATE…WHERE used_count<max_uses 的写锁串行化保证不超额。
    async with pg_pool.acquire() as conn:
        user_id = await _seed_user(conn)
        await create_invite(conn, code_hash="hash-race", created_by_user_id=user_id)

    async def attempt() -> bool:
        async with pg_pool.acquire() as c:
            return await consume_invite(c, code_hash="hash-race", user_id=user_id)

    results = await asyncio.gather(attempt(), attempt())
    assert sum(1 for r in results if r) == 1  # 恰好一个成功

    async with pg_pool.acquire() as conn:
        rows = await list_invites(conn, limit=10)
        race = next(r for r in rows if r["used_count"] >= 1)
        assert race["used_count"] == 1  # 绝不超额

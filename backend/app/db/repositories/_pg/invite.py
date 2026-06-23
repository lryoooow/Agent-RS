from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


async def create_invite(
    conn,
    *,
    code_hash: str,
    created_by_user_id: str,
    label: str = "",
    expires_at: datetime | None = None,
    max_uses: int = 1,
) -> dict[str, Any]:
    """新建一条邀请。只存 code_hash（HMAC），不存明文。返回插入行（不含明文码）。"""
    row = await conn.fetchrow(
        """
        INSERT INTO agent_rs.invites (
          code_hash, label, created_by_user_id, expires_at, max_uses
        )
        VALUES ($1, $2, $3::uuid, $4, $5)
        RETURNING id::text, label, created_by_user_id::text, expires_at,
                  max_uses, used_count, used_by_user_id::text, used_at, revoked, created_at
        """,
        code_hash,
        label,
        created_by_user_id,
        expires_at,
        max_uses,
    )
    return dict(row)


async def consume_invite(conn, *, code_hash: str, user_id: str) -> bool:
    """原子消费邀请：仅当未撤销、未过期、未用满时 used_count+1 并记录消费者。

    并发安全核心：单条 UPDATE…WHERE 把"校验有效"和"占用名额"合并为一个原子操作，
    两个请求同时拿同一张单次码时，只有一个的 WHERE 命中（used_count < max_uses 失败给另一个），
    RETURNING 有行 = 本次成功消费。无需显式行锁，靠 UPDATE 的写锁串行化。
    返回 True=消费成功；False=码无效/已用满/已过期/已撤销。
    """
    row = await conn.fetchrow(
        """
        UPDATE agent_rs.invites
        SET used_count = used_count + 1,
            used_by_user_id = $2::uuid,
            used_at = now()
        WHERE code_hash = $1
          AND revoked = false
          AND used_count < max_uses
          AND (expires_at IS NULL OR expires_at > now())
        RETURNING id::text
        """,
        code_hash,
        user_id,
    )
    return row is not None


async def list_invites(conn, *, limit: int = 100) -> list[dict[str, Any]]:
    """管理界面邀请列表，按创建时间倒序。不返回 code_hash（无意义且属敏感派生物）。"""
    rows = await conn.fetch(
        """
        SELECT id::text, label, created_by_user_id::text, expires_at,
               max_uses, used_count, used_by_user_id::text, used_at, revoked, created_at
        FROM agent_rs.invites
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [dict(row) for row in rows]


async def revoke_invite(conn, *, invite_id: str) -> bool:
    """撤销邀请（软删）。返回是否命中一行。已撤销/不存在返回 False。"""
    result = await conn.execute(
        """
        UPDATE agent_rs.invites
        SET revoked = true
        WHERE id = $1::uuid AND revoked = false
        """,
        invite_id,
    )
    return result.endswith(" 1")

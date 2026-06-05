from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


async def find_user_by_email(conn, *, email: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT id::text, email, password_hash, name, email_verified, is_active, created_at
        FROM agent_rs.users
        WHERE lower(email) = lower($1)
        """,
        email,
    )
    return dict(row) if row else None


async def get_user_by_id(conn, *, user_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT id::text, email, name, email_verified, is_active, created_at
        FROM agent_rs.users
        WHERE id = $1::uuid
        """,
        user_id,
    )
    return dict(row) if row else None


async def create_user(conn, *, email: str, password_hash: str, name: str) -> dict[str, Any]:
    user_id = str(uuid.uuid4())
    row = await conn.fetchrow(
        """
        INSERT INTO agent_rs.users (
          id, email, password_hash, name, email_verified, is_active
        )
        VALUES ($1::uuid, lower($2), $3, $4, false, true)
        RETURNING id::text, email, name, email_verified, is_active, created_at
        """,
        user_id,
        email,
        password_hash,
        name,
    )
    return dict(row)


async def create_session(
    conn,
    *,
    user_id: str,
    token_hash: str,
    days: int,
) -> dict[str, Any]:
    expires_at = datetime.now(timezone.utc) + timedelta(days=days)
    row = await conn.fetchrow(
        """
        INSERT INTO agent_rs.sessions (user_id, token_hash, expires_at)
        VALUES ($1::uuid, $2, $3)
        RETURNING id::text, user_id::text, token_hash, expires_at, created_at, last_seen_at
        """,
        user_id,
        token_hash,
        expires_at,
    )
    return dict(row)


async def ensure_workspace_membership(
    conn,
    *,
    workspace_id: str,
    user_id: str,
    role: str = "member",
) -> None:
    await conn.execute(
        """
        INSERT INTO agent_rs.memberships (id, workspace_id, user_id, role)
        VALUES (gen_random_uuid(), $1::uuid, $2::uuid, $3)
        ON CONFLICT (workspace_id, user_id) DO NOTHING
        """,
        workspace_id,
        user_id,
        role,
    )


async def find_user_by_session(conn, *, token_hash: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT u.id::text, u.email, u.name, u.email_verified, u.is_active, u.created_at
        FROM agent_rs.sessions s
        JOIN agent_rs.users u ON u.id = s.user_id
        WHERE s.token_hash = $1
          AND s.expires_at > now()
          AND u.is_active = true
        """,
        token_hash,
    )
    if row is None:
        return None
    await conn.execute(
        "UPDATE agent_rs.sessions SET last_seen_at = now() WHERE token_hash = $1",
        token_hash,
    )
    return dict(row)


async def delete_session(conn, *, token_hash: str) -> bool:
    result = await conn.execute("DELETE FROM agent_rs.sessions WHERE token_hash = $1", token_hash)
    return result.endswith(" 1")


async def prune_expired_sessions(conn) -> int:
    result = await conn.execute("DELETE FROM agent_rs.sessions WHERE expires_at <= now()")
    return int(result.rsplit(" ", 1)[-1])

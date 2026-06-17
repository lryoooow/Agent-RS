from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any


def _utc_text(dt: datetime) -> str:
    """格式化为 'YYYY-MM-DD HH:MM:SS' UTC 文本。

    与 SQLite CURRENT_TIMESTAMP 同格式，使 expires_at > CURRENT_TIMESTAMP 的
    词法比较成立（tz-aware ISO 的 '+00:00' 会破坏比较，必须剥掉）。
    """
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def find_user_by_email(conn, *, email: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT id, email, password_hash, name, email_verified, is_active, created_at
        FROM users
        WHERE lower(email) = lower(?)
        """,
        email,
    )
    return dict(row) if row else None


async def get_user_by_id(conn, *, user_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT id, email, name, email_verified, is_active, created_at
        FROM users
        WHERE id = ?
        """,
        user_id,
    )
    return dict(row) if row else None


async def create_user(conn, *, email: str, password_hash: str, name: str) -> dict[str, Any]:
    user_id = str(uuid.uuid4())
    row = await conn.fetchrow(
        """
        INSERT INTO users (id, email, password_hash, name, email_verified, is_active)
        VALUES (?, lower(?), ?, ?, 0, 1)
        RETURNING id, email, name, email_verified, is_active, created_at
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
    expires_at = _utc_text(datetime.now(timezone.utc) + timedelta(days=days))
    row = await conn.fetchrow(
        """
        INSERT INTO sessions (id, user_id, token_hash, expires_at)
        VALUES (?, ?, ?, ?)
        RETURNING id, user_id, token_hash, expires_at, created_at, last_seen_at
        """,
        str(uuid.uuid4()),
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
        INSERT INTO memberships (id, workspace_id, user_id, role)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (workspace_id, user_id) DO NOTHING
        """,
        str(uuid.uuid4()),
        workspace_id,
        user_id,
        role,
    )


async def find_user_by_session(conn, *, token_hash: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        """
        SELECT u.id, u.email, u.name, u.email_verified, u.is_active, u.created_at
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = ?
          AND s.expires_at > CURRENT_TIMESTAMP
          AND u.is_active = 1
        """,
        token_hash,
    )
    if row is None:
        return None
    await conn.execute(
        "UPDATE sessions SET last_seen_at = CURRENT_TIMESTAMP WHERE token_hash = ?",
        token_hash,
    )
    return dict(row)


async def delete_session(conn, *, token_hash: str) -> bool:
    rowcount = await conn.execute("DELETE FROM sessions WHERE token_hash = ?", token_hash)
    return rowcount == 1


async def prune_expired_sessions(conn) -> int:
    rowcount = await conn.execute("DELETE FROM sessions WHERE expires_at <= CURRENT_TIMESTAMP")
    return int(rowcount)

from __future__ import annotations

import logging

from app.lib.auth.security import hash_session_token
from app.lib.db.pool import fetch_optional_pool
from app.lib.db.repositories.auth import find_user_by_session
from app.shared.settings import get_settings

logger = logging.getLogger(__name__)


async def get_session_user(token: str | None) -> dict | None:
    settings = get_settings()
    if not settings.auth_enabled or not token:
        return None
    pool = await fetch_optional_pool()
    if pool is None:
        return None
    token_hash = hash_session_token(token, settings.auth_secret_key)
    try:
        async with pool.acquire() as conn:
            return await find_user_by_session(conn, token_hash=token_hash)
    except Exception:
        logger.exception("Failed to resolve session user.")
        return None

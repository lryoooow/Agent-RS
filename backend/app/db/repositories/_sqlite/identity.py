from __future__ import annotations

import uuid

from app.core.settings import Settings


async def ensure_default_identity(conn, settings: Settings) -> tuple[str, str]:
    await conn.execute(
        """
        INSERT INTO users (id, email, password_hash, name, email_verified, is_active)
        VALUES (?, ?, ?, ?, 1, 1)
        ON CONFLICT (email) DO UPDATE
        SET name = excluded.name,
            is_active = 1
        """,
        settings.default_user_id,
        settings.default_user_email,
        "disabled",
        settings.default_user_name,
    )
    await conn.execute(
        """
        INSERT INTO workspaces (id, name, slug, owner_user_id, metadata_json)
        VALUES (?, ?, ?, ?, '{}')
        ON CONFLICT (slug) DO UPDATE
        SET name = excluded.name
        """,
        settings.default_workspace_id,
        settings.default_workspace_name,
        settings.default_workspace_slug,
        settings.default_user_id,
    )
    await conn.execute(
        """
        INSERT INTO memberships (id, workspace_id, user_id, role)
        VALUES (?, ?, ?, 'owner')
        ON CONFLICT (workspace_id, user_id) DO NOTHING
        """,
        str(uuid.uuid4()),
        settings.default_workspace_id,
        settings.default_user_id,
    )
    return settings.default_user_id, settings.default_workspace_id

from __future__ import annotations

from app.shared.settings import Settings


async def ensure_default_identity(conn, settings: Settings) -> tuple[str, str]:
    await conn.execute(
        """
        INSERT INTO chatbot.users (
          id, email, password_hash, name, email_verified, is_active
        )
        VALUES ($1::uuid, $2, $3, $4, true, true)
        ON CONFLICT (email) DO UPDATE
        SET name = EXCLUDED.name,
            is_active = true
        """,
        settings.default_user_id,
        settings.default_user_email,
        "disabled",
        settings.default_user_name,
    )
    await conn.execute(
        """
        INSERT INTO chatbot.workspaces (
          id, name, slug, owner_user_id, metadata_json
        )
        VALUES ($1::uuid, $2, $3, $4::uuid, '{}'::jsonb)
        ON CONFLICT (slug) DO UPDATE
        SET name = EXCLUDED.name
        """,
        settings.default_workspace_id,
        settings.default_workspace_name,
        settings.default_workspace_slug,
        settings.default_user_id,
    )
    await conn.execute(
        """
        INSERT INTO chatbot.memberships (id, workspace_id, user_id, role)
        VALUES (gen_random_uuid(), $1::uuid, $2::uuid, 'owner')
        ON CONFLICT (workspace_id, user_id) DO NOTHING
        """,
        settings.default_workspace_id,
        settings.default_user_id,
    )
    return settings.default_user_id, settings.default_workspace_id

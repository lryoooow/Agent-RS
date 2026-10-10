from __future__ import annotations

from app.core.settings import Settings


async def ensure_default_identity(conn, settings: Settings) -> tuple[str, str]:
    # Read fast path avoids conflicting INSERTs/row locks on every chat turn.
    ready = await conn.fetchval("""
        SELECT EXISTS(SELECT 1 FROM agent_rs.users u
        JOIN agent_rs.memberships m ON m.user_id=u.id
        JOIN agent_rs.workspaces w ON w.id=m.workspace_id
        WHERE u.id=$1::uuid AND u.email=$2 AND w.id=$3::uuid AND w.slug=$4 AND w.owner_user_id=u.id)
        """,settings.default_user_id,settings.default_user_email,
        settings.default_workspace_id,settings.default_workspace_slug)
    if ready: return settings.default_user_id, settings.default_workspace_id
    await conn.execute(
        """
        INSERT INTO agent_rs.users (
          id, email, password_hash, name, email_verified, is_active
        )
        VALUES ($1::uuid, $2, $3, $4, true, true)
        ON CONFLICT DO NOTHING
        """,
        settings.default_user_id,
        settings.default_user_email,
        "disabled",
        settings.default_user_name,
    )
    user_matches = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM agent_rs.users WHERE id=$1::uuid AND email=$2)",
        settings.default_user_id, settings.default_user_email)
    if not user_matches:
        raise RuntimeError("Default identity configuration conflicts with existing records.")
    await conn.execute(
        """
        INSERT INTO agent_rs.workspaces (
          id, name, slug, owner_user_id, metadata_json
        )
        VALUES ($1::uuid, $2, $3, $4::uuid, '{}'::jsonb)
        ON CONFLICT DO NOTHING
        """,
        settings.default_workspace_id,
        settings.default_workspace_name,
        settings.default_workspace_slug,
        settings.default_user_id,
    )
    workspace_matches = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM agent_rs.workspaces WHERE id=$1::uuid AND slug=$2 AND owner_user_id=$3::uuid)",
        settings.default_workspace_id, settings.default_workspace_slug, settings.default_user_id)
    if not workspace_matches:
        raise RuntimeError("Default workspace configuration conflicts with existing records.")
    await conn.execute(
        """
        INSERT INTO agent_rs.memberships (id, workspace_id, user_id, role)
        VALUES (gen_random_uuid(), $1::uuid, $2::uuid, 'owner')
        ON CONFLICT (workspace_id, user_id) DO NOTHING
        """,
        settings.default_workspace_id,
        settings.default_user_id,
    )
    return settings.default_user_id, settings.default_workspace_id

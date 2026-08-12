from __future__ import annotations

from typing import Any

from app.agent.imagery_access import user_owns_imagery
from app.agent.tool_registry import get_tool
from app.db.pool import fetch_optional_pool
from app.db.repositories.document import get_document


async def validate_tool_access(tool_name: str, arguments: dict[str, Any], user_id: str | None) -> str | None:
    tool = get_tool(tool_name)
    if tool is None:
        return None
    if tool.resource_kind == "document":
        if not user_id:
            return "owner_required"
        document_id = str(arguments.get("document_id") or "")
        pool = await fetch_optional_pool()
        if pool is None:
            return "document_not_found_or_forbidden"
        try:
            async with pool.acquire() as conn:
                document = await get_document(
                    conn,
                    document_id=document_id,
                    user_id=user_id,
                )
        except Exception:
            return "document_not_found_or_forbidden"
        return None if document is not None else "document_not_found_or_forbidden"
    if tool.resource_kind != "imagery":
        return None
    imagery_id = str(arguments.get("imagery_id") or "")
    if not user_id:
        return "owner_required"
    if not await user_owns_imagery(imagery_id, user_id):
        return "imagery_not_found_or_forbidden"
    return None

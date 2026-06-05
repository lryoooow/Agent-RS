from __future__ import annotations

from typing import Any

from app.agent.imagery_access import user_owns_imagery


def validate_tool_access(tool_name: str, arguments: dict[str, Any], user_id: str | None) -> str | None:
    if tool_name != "calculate_ndvi":
        return None
    imagery_id = str(arguments.get("imagery_id") or "")
    if not user_id:
        return "owner_required"
    if not user_owns_imagery(imagery_id, user_id):
        return "imagery_not_found_or_forbidden"
    return None

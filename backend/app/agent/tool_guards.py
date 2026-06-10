from __future__ import annotations

from typing import Any

from app.agent.imagery_access import user_owns_imagery
from app.agent.routing import ALL_DOCUMENT_TOOLS, ALL_IMAGERY_TOOLS

_IMAGERY_TOOLS = set(ALL_IMAGERY_TOOLS)

# 文档工具吃 document_id，文档在 DB 里按 user_id 隔离（get_document 会按 owner 过滤）。
# 这里只做"必须有用户身份"的前置校验，真正的归属由 DB 查询保证。
_DOCUMENT_TOOLS = set(ALL_DOCUMENT_TOOLS)


def validate_tool_access(tool_name: str, arguments: dict[str, Any], user_id: str | None) -> str | None:
    if tool_name in _DOCUMENT_TOOLS:
        if not user_id:
            return "owner_required"
        return None
    if tool_name not in _IMAGERY_TOOLS:
        return None
    imagery_id = str(arguments.get("imagery_id") or "")
    if not user_id:
        return "owner_required"
    if not user_owns_imagery(imagery_id, user_id):
        return "imagery_not_found_or_forbidden"
    return None

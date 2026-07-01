from __future__ import annotations

from typing import Any

from app.agent.imagery_access import user_owns_imagery
from app.agent.routing import ALL_DOCUMENT_TOOLS, ALL_IMAGERY_TOOLS
from app.db.pool import fetch_optional_pool
from app.db.repositories.document import get_document

_IMAGERY_TOOLS = set(ALL_IMAGERY_TOOLS)

# 文档工具吃 document_id，文档在 DB 里按 user_id 隔离（get_document 会按 owner 过滤）。
# 这里只做"必须有用户身份"的前置校验，真正的归属由 DB 查询保证。
# 注：document_id 的 UUID 格式由 ParseDocumentArguments 的 pydantic pattern 在本 guard 之前
# 校验（plan_validator.py:54 / child.py:67 先 model_validate 再调本函数），故此处不再重复格式检查；
# 红队 hallucinated_document_id 穿透（编造的是合法格式 UUID）的根因修复在 planner prompt 层。
_DOCUMENT_TOOLS = set(ALL_DOCUMENT_TOOLS)


async def validate_tool_access(tool_name: str, arguments: dict[str, Any], user_id: str | None) -> str | None:
    if tool_name in _DOCUMENT_TOOLS:
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
    if tool_name not in _IMAGERY_TOOLS:
        return None
    imagery_id = str(arguments.get("imagery_id") or "")
    if not user_id:
        return "owner_required"
    if not await user_owns_imagery(imagery_id, user_id):
        return "imagery_not_found_or_forbidden"
    return None

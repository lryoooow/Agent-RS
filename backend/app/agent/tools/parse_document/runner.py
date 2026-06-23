from __future__ import annotations

import logging
from typing import Any

from app.agent.tools.common import execution_metadata
from app.agent.tools.parse_document.formatter import format_parse_document_context
from app.agent.tools.parse_document.schema import DOCUMENT_ID_PATTERN, ParseDocumentArguments
from app.agent.types import ToolRunResult
from app.auth.current_user import get_current_user_id
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool
from app.db.repositories.document import get_document

logger = logging.getLogger(__name__)


async def run_parse_document(args: ParseDocumentArguments) -> ToolRunResult:
    if not DOCUMENT_ID_PATTERN.fullmatch(args.document_id):
        return _error_result("解析文档参数无效: document_id 必须是 UUID。", "invalid_document_id")

    settings = get_settings()
    if not settings.storage_active:
        return _error_result("文档读取失败: 数据库未启用。", "database_disabled")

    pool = await fetch_optional_pool()
    if pool is None:
        return _error_result("文档读取失败: 数据库不可用。", "database_unavailable")

    user_id = get_current_user_id()
    try:
        async with pool.acquire() as conn:
            row = await get_document(conn, document_id=args.document_id, user_id=user_id)
    except Exception as exc:
        logger.exception("Parse document DB read failed: %s", exc)
        return _error_result("文档读取失败，请稍后重试或检查数据库状态。", "db_error")

    if row is None:
        return _error_result(
            f"文档 {args.document_id} 不存在或当前用户无权访问。", "document_not_found"
        )

    content = str(row.get("content") or "")
    if not content.strip():
        return _error_result(
            f"文档 {args.document_id} 没有可用的正文内容。", "document_empty"
        )

    full_length = len(content)
    limit = args.max_chars or settings.ai_context_max_tool_chars
    truncated = full_length > limit
    returned = content[:limit] if truncated else content

    metadata = _as_dict(row.get("metadata"))
    title = str(row.get("title") or "未命名文档")
    doc_type = row.get("doc_type")

    tool_context = format_parse_document_context(
        args.document_id,
        title=title,
        doc_type=doc_type,
        metadata=metadata,
        content=returned,
        truncated=truncated,
        full_length=full_length,
    )
    return ToolRunResult(
        tool_context=tool_context,
        result_count=1,
        query=f"parse_document({args.document_id})",
        metadata={
            **execution_metadata("process"),
            "document_id": args.document_id,
            "doc_type": doc_type,
            "full_length": full_length,
            "returned_chars": len(returned),
            "truncated": truncated,
        },
    )


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _error_result(message: str, code: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=message,
        error=code,
        metadata=execution_metadata("failed", error_code=code),
    )

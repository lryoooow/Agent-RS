from __future__ import annotations

import logging

from app.agent.report.builder import ReportError, build_conversation_report
from app.agent.tools.common import execution_metadata
from app.agent.tools.report.formatter import format_report_context
from app.agent.tools.report.schema import ReportArguments
from app.agent.types import AgentArtifact, ToolRunResult
from app.auth import get_current_conversation_id, get_current_user_id

logger = logging.getLogger(__name__)


async def run_report(args: ReportArguments) -> ToolRunResult:
    """对话工具 generate_report：把本对话真实分析结果汇总成可下载的 Word 报告。

    身份/对话来自请求级 contextvar（user 与 runtime.plan 设置的 conversation），
    不进 runner 签名；报告数据与归属校验全在 build_conversation_report 内完成。
    """
    user_id = get_current_user_id()
    conversation_id = get_current_conversation_id()

    try:
        artifact = await build_conversation_report(
            conversation_id=conversation_id,
            user_id=user_id,
            imagery_id=args.imagery_id,
        )
    except ReportError as exc:
        # 文案对用户安全（不含内部细节）；原始 code 进 logger 便于诊断。
        logger.info("Report not generated (%s): %s", exc.code, exc)
        return ToolRunResult(
            tool_context=f"{exc.message}",
            error=exc.code,
            metadata=execution_metadata("failed", error_code=exc.code),
        )
    except Exception as exc:
        logger.exception("Report generation unexpected error: %s", exc)
        return ToolRunResult(
            tool_context="报告生成失败，请稍后重试。",
            error="report_unexpected_error",
            metadata=execution_metadata("failed", error_code="report_unexpected_error"),
        )

    geospatial_result = {
        "type": "report",
        "imagery_id": artifact.imagery_id,
        "filename": artifact.filename,
        "download_url": artifact.download_url,
    }
    return ToolRunResult(
        tool_context=format_report_context(artifact),
        result_count=1,
        query=f"generate_report({artifact.imagery_id})",
        geospatial_result=geospatial_result,
        artifacts=[AgentArtifact(type="report", payload=geospatial_result)],
        metadata=execution_metadata("local"),
    )

"""web_search 的注册表 runner：把既有检索管线包成 ToolRunResult。

配额（AGENT_WEB_SEARCH_MAX_CALLS）不在这一层——它与 GPU 工具一样由
`engine/tools.py` 的 AutoGen 包装在执行前 `try_reserve` 强制。
"""

from __future__ import annotations

import logging

from app.agent.search.agent import run_web_search
from app.agent.search.credentials import resolve_tavily_api_key
from app.agent.search.schema import WebSearchArguments
from app.agent.types import ToolRunResult
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def web_search_tool_available() -> bool:
    """只有配置密钥且配额大于零时才注册检索工具。"""
    settings = get_settings()
    return bool(resolve_tavily_api_key() and settings.agent_web_search_max_calls > 0)


async def run_web_search_tool(args: WebSearchArguments) -> ToolRunResult:
    settings = get_settings()
    # 条数上限由服务端强制，模型说了不算——防止它自己要 100 条把上下文撑爆。
    clamped = args.clamped(settings.agent_web_search_max_results)

    try:
        result = await run_web_search(clamped)
    except Exception as exc:
        logger.exception("联网检索失败")
        return ToolRunResult(
            tool_context=f"检索失败：{exc}。请如实告知用户这次没能查到，不要编造内容。",
            query=args.query,
            error=str(exc),
        )

    if result.error:
        # run_web_search 的失败话术已含"请勿声称已完成实时联网检索"。
        return result
    if not result.result_count:
        # 零结果时明确邀请重试：这是此前搜索 Agent 提示词里"换词再查"行为的延续，
        # 现在挪到工具返回值里教调用方怎么做。
        return ToolRunResult(
            tool_context=(
                "本次检索没有返回有效结果。可以换一组检索词再试一次；"
                "若仍无结果，请如实告知用户没有查到，不要编造内容。"
            ),
            query=args.query,
        )
    return result

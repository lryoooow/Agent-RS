"""AutoGen 联网搜索 Agent。

把确定性的 `run_web_search` 包成工具交给 `AssistantAgent`，它可以：

- **改写检索词**：第一次没查到有用的，换个说法再来
- **多轮检索**：复合问题先查一个意图，看结果再决定第二个怎么查
- **来源自查**：结果自相矛盾或明显过期时，主动补一次检索而不是照抄

检索实现本身（Tavily 客户端、结果过滤、去重、格式化、缓存）一行不改。
"""

from __future__ import annotations

import logging

from autogen_agentchat.agents import AssistantAgent
from autogen_core import CancellationToken
from autogen_core.memory import Memory
from autogen_core.models import ChatCompletionClient
from autogen_core.tools import BaseTool

from app.agent.engine.agents import COMPLETION_PROTOCOL, ContextFactory
from app.agent.engine.context import BudgetedChatCompletionContext
from app.agent.engine.turn_context import (
    WEB_SEARCH_TOOL,
    ToolInvocation,
    current_turn_state,
)
from app.agent.search.agent import run_web_search
from app.agent.search.credentials import resolve_tavily_api_key
from app.agent.search.schema import WebSearchArguments
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

SEARCH_AGENT_NAME = "search_agent"
# 检索专家不持有遥感工具注册表中的工具，所以中文名在这里单独声明，
# 否则事件桥回落到原始 name，
# 前端会显示成「由 search_agent 处理」这种中英夹杂的字样。
SEARCH_AGENT_LABEL = "联网检索"

_SEARCH_SYSTEM_MESSAGE = """
你是 Agent-RS 的联网检索专家。用 web_search 工具查证实时、最新或需要外部来源的信息。

工作方式：
1. 先想清楚要查什么，写**聚焦**的检索词，不要把整句用户提问原样丢进去。
2. 复合问题（如"明天天气 + 出行攻略"）用 queries 给每个意图各写一条检索词。
3. 拿到结果先判断够不够：
   - 没查到有用信息 → 换个说法再查一次（换关键词、换角度、去掉限定词）
   - 结果自相矛盾或明显过期 → 补一次检索交叉验证
   - 已经够了 → 立刻停止检索，直接作答
4. 回答必须基于检索到的真实内容，标注来源；检索不到就如实说没查到，绝不编造。
5. 不要为了凑数反复检索——够用就停。

只回答当前这个问题，不要复述历史对话。
""".strip()


class WebSearchTool(BaseTool[WebSearchArguments, str]):
    """Tavily 检索工具。"""

    def __init__(self) -> None:
        super().__init__(
            args_type=WebSearchArguments,
            return_type=str,
            name=WEB_SEARCH_TOOL,
            description=(
                "检索公开网页。用于需要实时、最新、外部可验证信息的问题"
                "（天气、价格、政策、官网、最新数据集等）。"
            ),
        )

    async def run(self, args: WebSearchArguments, cancellation_token: CancellationToken) -> str:
        settings = get_settings()

        state = current_turn_state()
        # 检索按次计费，`AGENT_WEB_SEARCH_MAX_CALLS` 必须真的是上限。
        # Agent 能连续要工具，因此服务端必须在这里强制按回合计费配额。
        if state is not None and not state.try_reserve(WEB_SEARCH_TOOL):
            limit = state.quota_limit(WEB_SEARCH_TOOL)
            logger.info("联网检索被回合配额拦下（上限 %s 次）", limit)
            return (
                f"未执行检索：本轮联网检索已达上限（{limit} 次）。"
                "请基于已经查到的内容作答，并如实说明没有再次检索。不要编造内容。"
            )

        # 结果条数上限由服务端强制，模型说了不算——防止它自己要 100 条把上下文撑爆。
        clamped = args.clamped(settings.agent_web_search_max_results)

        try:
            result = await run_web_search(clamped)
        except Exception as exc:
            logger.exception("联网检索失败")
            return f"检索失败：{exc}。请如实告知用户这次没能查到，不要编造内容。"

        if state is not None:
            state.record(
                ToolInvocation(
                    name=WEB_SEARCH_TOOL, arguments=clamped.model_dump(), result=result
                )
            )

        if result.error:
            return f"检索未成功：{result.tool_context}。请如实告知用户，不要编造内容。"
        if not result.result_count:
            return (
                "本次检索没有返回有效结果。可以换一组检索词再试一次；"
                "若仍无结果，请如实告知用户没有查到。"
            )
        return result.tool_context


def build_search_agent(
    *,
    model_client: ChatCompletionClient,
    memory: list[Memory] | None = None,
    context_factory: ContextFactory | None = None,
) -> AssistantAgent:
    settings = get_settings()
    return AssistantAgent(
        name=SEARCH_AGENT_NAME,
        description="联网检索专家，负责查证实时、最新或需要外部来源的信息（天气、价格、政策、官网等）。",
        model_client=model_client,
        tools=[WebSearchTool()],
        system_message=f"{_SEARCH_SYSTEM_MESSAGE}\n\n{COMPLETION_PROTOCOL}",
        model_context=context_factory() if context_factory else BudgetedChatCompletionContext(),
        memory=memory or None,
        # 多轮检索的上限。与遥感工具共用同一个设置：都是"模型能连续要几次工具"。
        max_tool_iterations=max(1, settings.agent_max_tool_iterations),
        reflect_on_tool_use=True,
        model_client_stream=True,
    )


def search_agent_available() -> bool:
    """只有配置密钥且配额大于零时才组装搜索 Agent。"""
    settings = get_settings()
    return bool(resolve_tavily_api_key() and settings.agent_web_search_max_calls > 0)

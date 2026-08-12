"""把 12 个遥感工具包成 AutoGen Tool。

## 核心约束：安全管线不许绕过

每个包装器内部走的是 `app/agent/tool_execution.py` 那一份共享管线
（可用性 → 参数模型 → **归属鉴权** → durable 队列 → staging → runner → 终态落库），
这里**不重新实现任何安全或执行步骤**。

多步链路下这点尤其要紧：模型可能连续要 3 个工具，中间步骤的 `imagery_id` 是它现编的，
所以**每一步都要各自过鉴权**，不存在"第一步过了后面放行"。

## 身份从哪来

AutoGen 的工具签名里没有 `user_id`，塞进参数模型又等于让模型自己声明身份（灾难）。
所以走请求级 contextvar `app.auth.peek_current_user_id()`——注意是 `peek_` 而不是
`get_current_user_id()`，后者未设置时会回退成默认用户，等于把匿名请求当登录用户放行。

## 返回值只给模型看文本

`run()` 返回 `ToolRunResult.tool_context`（已经是给模型消费的摘要）。
图层、执行详情等产物不进返回值，改由 `turn_context` 收集，编排层回合结束时取走。
理由见 turn_context 的模块文档。
"""

from __future__ import annotations

import logging
from typing import Any

from autogen_core import CancellationToken
from autogen_core.tools import BaseTool
from pydantic import BaseModel

from app.agent.engine.turn_context import (
    GPU_HEAVY_TOOLS,
    ToolInvocation,
    current_turn_state,
)
from app.agent.tool_execution import PrepareRejected, prepare_tool_call, run_prepared_tool
from app.agent.tool_registry import TOOLS, RegisteredTool
from app.agent.types import ToolRunResult
from app.auth import peek_current_user_id
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


class RemoteSensingTool(BaseTool[BaseModel, str]):
    """单个已注册工具的 AutoGen 包装。"""

    def __init__(self, tool: RegisteredTool) -> None:
        definition = tool.definition.get("function", {})
        super().__init__(
            args_type=tool.argument_model,
            return_type=str,
            name=tool.name,
            description=definition.get("description", "") or tool.name,
        )
        self._tool = tool

    async def run(self, args: BaseModel, cancellation_token: CancellationToken) -> str:
        state = current_turn_state()

        # GPU 配额：**执行前**占名额（并行工具调用下"跑完再记账"拦不住，
        # 详见 turn_context 模块文档）。超了就如实告诉模型让它自己收敛，
        # 而不是抛异常炸链路。
        if state is not None and not state.try_reserve(self._tool.name):
            limit = state.quota_limit(self._tool.name)
            logger.info("GPU 工具 %s 被回合配额拦下（上限 %s）", self._tool.name, limit)
            return (
                f"未执行 {self._tool.name}：本轮 GPU 重工具调用已达上限（{limit} 次）。"
                "请先基于已有结果回答，并告知用户这一步需要下一轮单独执行。"
                "不要假装已经执行过，也不要编造结果。"
            )

        user_id = peek_current_user_id()
        arguments = args.model_dump()
        if state is not None:
            arguments = state.arguments_for(self._tool.name, arguments)

        # 审计日志：多步链路下一个回合可能有 5 次工具调用，出问题时需要能回溯
        # 「谁、用什么身份、对哪个资源」调了什么。这里是唯一同时掌握这三样的位置。
        logger.info(
            "tool.invoke name=%s user=%s imagery=%s document=%s",
            self._tool.name,
            user_id or "<anonymous>",
            arguments.get("imagery_id") or "-",
            arguments.get("document_id") or "-",
        )

        prepared = await prepare_tool_call(self._tool.name, arguments, user_id=user_id)
        if isinstance(prepared, PrepareRejected):
            # 拒绝一律留痕：鉴权失败尤其要能在日志里查到。
            logger.warning(
                "tool.rejected name=%s user=%s reason=%s detail=%s",
                self._tool.name,
                user_id or "<anonymous>",
                prepared.failure,
                prepared.error_detail,
            )
            # 没真跑就把名额还回去，否则一次参数写错就白白吃掉本轮的 GPU 配额。
            if state is not None:
                state.release(self._tool.name)
            self._record(state, arguments, prepared.result)
            return self._rejection_text(prepared)

        result = await run_prepared_tool(prepared)
        self._record(state, arguments, result)

        if result.error:
            return (
                f"{self._tool.name} 执行失败：{result.tool_context}"
                "\n请如实告知用户这一步没有成功，不要编造结果。"
            )
        return result.tool_context

    def _record(self, state, arguments: dict[str, Any], result: ToolRunResult) -> None:
        if state is None:
            # 没有回合作用域（单测直接调用工具等场景）：产物无处可收，但执行本身有效。
            logger.debug("工具 %s 在回合作用域之外执行，产物未收集", self._tool.name)
            return
        state.record(ToolInvocation(name=self._tool.name, arguments=arguments, result=result))

    def _rejection_text(self, rejected: PrepareRejected) -> str:
        # 把拒绝原因翻译成模型能据以调整行为的话术。
        # 关键：明确禁止编造结果——被拒之后模型最常见的失败模式就是「假装做过了」。
        hints = {
            "tool_unavailable": (
                f"未执行 {self._tool.name}：该工具当前不可用。请如实告知用户，不要编造结果。"
            ),
            "invalid_arguments": (
                f"未执行 {self._tool.name}：参数不符合要求（{rejected.error_detail}）。"
                "请检查参数后重试；若缺少必要信息，请向用户询问，不要编造结果。"
            ),
            "access_denied": (
                f"未执行 {self._tool.name}：当前用户无权访问该资源"
                f"（{rejected.error_detail}）。请让用户确认资源 ID 是否属于自己。"
                "不要改用其它 ID 重试，也不要编造结果。"
            ),
        }
        return hints[rejected.failure]


def build_tools(names: tuple[str, ...] | None = None) -> list[RemoteSensingTool]:
    """构造工具包装列表。

    Args:
        names: 只包这些工具（领域 Agent 用来限定自己的工具集）。None = 全部已启用工具。
    """
    selected = TOOLS if names is None else {n: TOOLS[n] for n in names if n in TOOLS}
    return [RemoteSensingTool(tool) for tool in selected.values() if tool.is_enabled()]


def build_tool_map() -> dict[str, RemoteSensingTool]:
    return {tool.name: tool for tool in build_tools()}

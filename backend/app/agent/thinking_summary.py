"""可展示的阶段摘要。

本模块刻意不接收模型文本、reasoning、工具参数或路由 reason。页面能看到的内容只能由
固定枚举映射产生；否则所谓“摘要”仍可能把内部推理换个事件名继续泄漏。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agent.types import AgentStage

ThinkingSummaryStage = Literal[
    "context",
    "routing",
    "planning",
    "tool",
    "verification",
    "answer",
]

SUMMARY_LABELS: dict[ThinkingSummaryStage, str] = {
    "context": "正在整理对话上下文与可用资料",
    "routing": "正在选择合适的处理流程",
    "planning": "已确定由合适的专业代理处理",
    "tool": "正在执行任务所需的分析工具",
    "verification": "正在核对工具结果与输出",
    "answer": "正在组织最终答复",
}

_STAGE_BY_AGENT_EVENT: dict[AgentStage, ThinkingSummaryStage] = {
    "context_assembled": "context",
    "routing_selected": "routing",
    "agent_selected": "planning",
    "tool_requested": "tool",
    "child_agent_running": "tool",
    "tool_execution_started": "tool",
    "tool_execution_completed": "verification",
    "tool_execution_failed": "verification",
    "tool_context_ready": "verification",
    "geospatial_result_ready": "verification",
    "final_answering": "answer",
}


@dataclass
class ThinkingSummaryTracker:
    """每个阶段最多发一次，且事件正文只来自固定映射。"""

    seen: set[ThinkingSummaryStage] = field(default_factory=set)

    def advance(self, stage: ThinkingSummaryStage) -> dict[str, str] | None:
        if stage in self.seen:
            return None
        self.seen.add(stage)
        return {"stage": stage, "label": SUMMARY_LABELS[stage]}

    def advance_for_agent_event(self, stage: AgentStage) -> dict[str, str] | None:
        return self.advance(_STAGE_BY_AGENT_EVENT[stage])

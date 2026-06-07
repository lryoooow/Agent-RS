from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from app.agent.child import ToolChildAgent
from app.agent.types import AgentEvent, AgentTrace, RuntimeToolCall, ToolRunResult

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]

# 工具 -> 领域子 agent 的归属表（单一数据源）。
# 新增工具时只在这里登记归属，runtime 自动按领域派发。
TOOL_DOMAIN: dict[str, str] = {
    "raster_inspect": "spectral_agent",
    "calculate_ndvi": "spectral_agent",
    "calculate_spectral_index": "spectral_agent",
    "render_band_composite": "spectral_agent",
    "segment_landcover": "segmentation_agent",
    "detect_objects": "detection_agent",
}

DOMAIN_LABELS: dict[str, str] = {
    "spectral_agent": "指数分析",
    "segmentation_agent": "地物分类",
    "detection_agent": "目标检测",
}


def domain_for_tool(tool_name: str) -> str | None:
    """返回工具所属领域子 agent 名；未登记返回 None。"""
    return TOOL_DOMAIN.get(tool_name)


class DomainToolAgent:
    """领域子 agent：维护自己的局部上下文（领域名 + child_run_id），
    在外层标识"我是哪个领域专家"，再委托已验证的 ToolChildAgent 执行实际工具。
    工具执行逻辑零重写，仅在其上叠加领域级 trace 上下文。"""

    def __init__(self, domain_name: str, *, parent_run_id: str | None = None) -> None:
        self.domain_name = domain_name
        self.domain_label = DOMAIN_LABELS.get(domain_name, domain_name)
        self.parent_run_id = parent_run_id or uuid.uuid4().hex

    async def run(
        self,
        tool_call: RuntimeToolCall,
        *,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
    ) -> ToolRunResult:
        child_run_id = uuid.uuid4().hex
        event = trace.add(
            "child_agent_running",
            f"{self.domain_label}子 Agent 接管：{tool_call.name}",
            tool_name=tool_call.name,
            agent_name=self.domain_name,
            domain=self.domain_name,
            domain_label=self.domain_label,
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="agent",
            dispatch_kind="tool",
        )
        if on_event:
            await on_event(event)

        # 委托给已验证的工具执行器；领域 agent 的 child_run_id 作为其 parent，
        # 形成 顶层 -> 领域 agent -> 工具执行 的上下文链。
        return await ToolChildAgent(parent_run_id=child_run_id).run(
            tool_call,
            user_id=user_id,
            trace=trace,
            on_event=on_event,
        )

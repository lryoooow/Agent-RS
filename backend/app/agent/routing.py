from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.schemas.chat import ChatRequest

ALL_IMAGERY_TOOLS = (
    "calculate_ndvi",
    "raster_inspect",
    "calculate_spectral_index",
    "render_band_composite",
    "detect_objects",
    "segment_landcover",
    "cloud_shadow_mask",
    "extract_water_mask",
    "clip_reproject_raster",
    "ocr_recognize",
)

# 文档工具走第二通道：吃 document_id（UUID）而非 imagery_id，
# 因此与影像工具分开登记。新增文档工具时在此追加，并由回归测试守住。
ALL_DOCUMENT_TOOLS = (
    "parse_document",
)

# 报告工具自成一类：不吃 imagery_id/document_id，读本对话已持久化的分析结果出 Word。
# 单列以便 plan_validator 的 route 白名单放行（candidate_tools 校验），
# 且不被 tool_guards 的影像/文档归属校验拦截（其归属由 build_conversation_report 内的对话校验保证）。
ALL_REPORT_TOOLS = (
    "generate_report",
)

ALL_CANDIDATE_TOOLS = ALL_IMAGERY_TOOLS + ALL_DOCUMENT_TOOLS + ALL_REPORT_TOOLS


@dataclass(frozen=True)
class AgentBudgets:
    max_tool_calls: int = 1
    max_child_agent_calls: int = 1


@dataclass(frozen=True)
class AgentRoute:
    mode: Literal["direct_chat", "full_pipeline"]
    reason: str
    candidate_tools: tuple[str, ...] = ()
    candidate_agents: tuple[str, ...] = ()
    skip_retrieval: bool = False
    budgets: AgentBudgets = field(default_factory=AgentBudgets)


def build_agent_route(query: str, request: ChatRequest) -> AgentRoute:
    if not query.strip():
        return AgentRoute(
            mode="direct_chat",
            reason="empty_query",
            skip_retrieval=True,
        )
    return AgentRoute(
        mode="full_pipeline",
        reason="llm_planner_route",
        candidate_tools=ALL_CANDIDATE_TOOLS,
        candidate_agents=("web_search",),
        skip_retrieval=False,
    )

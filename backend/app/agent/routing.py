from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agent.router import RequestRoute, classify_request_route
from app.agent.prompting.scenarios import wants_imagery_tool, wants_ndvi_calculation
from app.agent.safety_policy import SafetyPolicy
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest

ALL_IMAGERY_TOOLS = (
    "calculate_ndvi",
    "raster_inspect",
    "calculate_spectral_index",
    "render_band_composite",
    "detect_objects",
    "segment_landcover",
)


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
    if get_settings().agent_planner_mode.strip().lower() == "llm":
        safety = SafetyPolicy().decide(query)
        if safety.action == "skip":
            return AgentRoute(
                mode="direct_chat",
                reason=safety.reason,
                skip_retrieval=True,
            )
        return AgentRoute(
            mode="full_pipeline",
            reason="llm_planner_route",
            candidate_tools=ALL_IMAGERY_TOOLS,
            candidate_agents=("web_search",),
            skip_retrieval=False,
        )

    route = classify_request_route(query, request)
    if route == RequestRoute.DIRECT_CHAT:
        if wants_ndvi_calculation(query) or wants_imagery_tool(query):
            return AgentRoute(
                mode="full_pipeline",
                reason="imagery_tool_override",
                candidate_tools=ALL_IMAGERY_TOOLS,
                skip_retrieval=False,
            )
        return AgentRoute(
            mode=route.value,
            reason="direct_chat_route",
            skip_retrieval=True,
        )
    return AgentRoute(
        mode=route.value,
        reason="full_pipeline_route",
        candidate_tools=ALL_IMAGERY_TOOLS,
        candidate_agents=("web_search",),
        skip_retrieval=False,
    )

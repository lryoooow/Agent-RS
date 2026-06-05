from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agent.router import RequestRoute, classify_request_route
from app.agent.prompting.scenarios import wants_ndvi_calculation
from app.schemas.chat import ChatRequest


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
    route = classify_request_route(query, request)
    if route == RequestRoute.DIRECT_CHAT:
        if wants_ndvi_calculation(query):
            return AgentRoute(
                mode="full_pipeline",
                reason="ndvi_override",
                candidate_tools=("calculate_ndvi",),
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
        candidate_tools=("calculate_ndvi",),
        candidate_agents=("web_search",),
        skip_retrieval=False,
    )

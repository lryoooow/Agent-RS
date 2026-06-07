from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.agent.capability_registry import is_capability_enabled
from app.agent.config import ResolvedAIConfig
from app.agent.intent_policy import IntentDecision, IntentPolicy
from app.agent.llm_planner import LLMCapabilityPlanner, PlannerDecision, capability_snapshot
from app.agent.plan_validator import PlanValidator
from app.agent.routing import AgentRoute
from app.agent.safety_policy import SafetyPolicy
from app.agent.search.cache import get_planner_decision_cache
from app.agent.search_planner import SearchPlanner
from app.agent.types import AgentEvent, AgentTrace, RuntimeAgentCall, RuntimeToolCall
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]

_DEFAULT_TOOLS = {
    "calculate_ndvi",
    "raster_inspect",
    "calculate_spectral_index",
    "render_band_composite",
    "detect_objects",
    "segment_landcover",
}

_GUARD_ERROR_CODES = {"imagery_not_found_or_forbidden", "owner_required"}


@dataclass(frozen=True)
class TaskSelection:
    tool_call: RuntimeToolCall | None = None
    agent_call: RuntimeAgentCall | None = None
    reason: str = "no_tool"


class TaskSelector:
    async def select(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        query: str,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        add_event: Callable[..., Awaitable[AgentEvent]],
        route: AgentRoute | None = None,
    ) -> TaskSelection:
        if get_settings().agent_planner_mode.strip().lower() == "llm":
            return await self._select_with_llm_planner(
                client=client,
                config=config,
                request=request,
                query=query,
                user_id=user_id,
                trace=trace,
                on_event=on_event,
                add_event=add_event,
                route=route,
            )
        return await self._select_legacy(
            client=client,
            config=config,
            request=request,
            query=query,
            user_id=user_id,
            trace=trace,
            on_event=on_event,
            add_event=add_event,
            route=route,
        )

    async def _select_legacy(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        query: str,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        add_event: Callable[..., Awaitable[AgentEvent]],
        route: AgentRoute | None,
    ) -> TaskSelection:
        allowed_tools = set(route.candidate_tools) if route else _DEFAULT_TOOLS
        allowed_agents = set(route.candidate_agents) if route else {"web_search"}
        web_search_available = is_capability_enabled("web_search")

        decision = IntentPolicy().decide(
            request=request,
            query=query,
            user_id=user_id,
            config=config,
            web_search_available=web_search_available,
        )

        if decision.action == "skip":
            await self._emit_decision_event(decision, trace, on_event, add_event)
            return TaskSelection(reason=decision.reason)

        if decision.action == "ask_planner":
            if "web_search" not in allowed_agents:
                await add_event(trace, on_event, "tool_unavailable", "当前路由不允许联网搜索")
                return TaskSelection(reason="search_not_allowed_by_route")
            agent_call = await SearchPlanner().plan(
                client=client,
                config=config,
                request=request,
                query=query,
                user_id=user_id,
                web_search_available=web_search_available,
                trace=trace,
                on_event=on_event,
                add_event=add_event,
            )
            return TaskSelection(
                agent_call=agent_call,
                reason="planner" if agent_call else "planner_no_tool",
            )

        if decision.capability_kind == "tool":
            return await self._select_tool(
                decision=decision,
                allowed_tools=allowed_tools,
            )

        if decision.capability_kind == "agent":
            return await self._select_agent(
                decision=decision,
                allowed_agents=allowed_agents,
                web_search_available=web_search_available,
                trace=trace,
                on_event=on_event,
                add_event=add_event,
            )

        return TaskSelection(reason=decision.reason)

    async def _select_with_llm_planner(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        query: str,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        add_event: Callable[..., Awaitable[AgentEvent]],
        route: AgentRoute | None,
    ) -> TaskSelection:
        safety = SafetyPolicy().decide(query)
        if safety.action == "skip":
            await add_event(trace, on_event, "planner_no_call", "无需调用能力，直接回答", reason=safety.reason)
            return TaskSelection(reason=safety.reason)

        capabilities = capability_snapshot()
        scope = _planner_cache_scope(config=config, route=route, capabilities=capabilities, user_id=user_id, request=request)
        cache = get_planner_decision_cache()
        cached = cache.get_plan(query, scope=scope)
        if cached:
            decision = PlannerDecision(
                action=str(cached.get("action") or "none"),
                capability=cached.get("capability") if isinstance(cached.get("capability"), str) else None,
                arguments=cached.get("arguments") if isinstance(cached.get("arguments"), dict) else {},
                reason=str(cached.get("reason") or "cached_planner_decision"),
                raw=cached,
            )
        else:
            decision = await LLMCapabilityPlanner().plan(
                client=client,
                config=config,
                request=request,
                query=query,
                user_id=user_id,
                capabilities=capabilities,
                trace=trace,
                on_event=on_event,
                add_event=add_event,
            )

        validated = PlanValidator().validate(decision, route=route, user_id=user_id)
        if validated.validation_error:
            stage = (
                "capability_guard_rejected"
                if validated.validation_error in _GUARD_ERROR_CODES
                else "plan_validation_failed"
            )
            label = (
                "能力调用被拒绝，降级为直接回答"
                if stage == "capability_guard_rejected"
                else "能力规划校验失败，降级为直接回答"
            )
            await add_event(
                trace,
                on_event,
                stage,
                label,
                capability=validated.capability_name,
                error=validated.validation_error,
            )
            return TaskSelection(reason=validated.validation_error)
        if validated.action == "none":
            await add_event(trace, on_event, "planner_no_call", "规划结果无需调用能力", reason=validated.reason)
            return TaskSelection(reason=validated.reason or "planner_no_call")

        if not cached:
            cache.put_plan(
                query,
                {
                    "action": "call",
                    "capability": validated.capability_name,
                    "arguments": validated.arguments,
                    "reason": validated.reason,
                },
                scope=scope,
            )

        await add_event(
            trace,
            on_event,
            "planner_selected",
            "规划选择能力调用",
            capability=validated.capability_name,
            dispatch_kind=validated.capability_kind,
            reason=validated.reason,
            cached=bool(cached),
        )
        return TaskSelection(
            tool_call=validated.tool_call,
            agent_call=validated.agent_call,
            reason=validated.reason or "llm_planner",
        )

    async def _select_tool(
        self,
        *,
        decision: IntentDecision,
        allowed_tools: set[str],
    ) -> TaskSelection:
        if not decision.capability_name or not decision.tool_call:
            return TaskSelection(reason=decision.reason)
        if decision.capability_name not in allowed_tools:
            if decision.capability_name == "calculate_ndvi":
                return TaskSelection(reason="ndvi_not_allowed_by_route")
            return TaskSelection(reason=f"{decision.capability_name}_not_allowed_by_route")
        if not is_capability_enabled(decision.capability_name):
            return TaskSelection(reason=f"{decision.capability_name}_unavailable")
        return TaskSelection(tool_call=decision.tool_call, reason=decision.reason)

    async def _select_agent(
        self,
        *,
        decision: IntentDecision,
        allowed_agents: set[str],
        web_search_available: bool,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        add_event: Callable[..., Awaitable[AgentEvent]],
    ) -> TaskSelection:
        if not decision.capability_name or not decision.agent_call:
            return TaskSelection(reason=decision.reason)
        if decision.capability_name not in allowed_agents:
            await add_event(trace, on_event, "tool_unavailable", "当前路由不允许联网搜索")
            return TaskSelection(reason="search_not_allowed_by_route")
        if not web_search_available:
            await add_event(trace, on_event, "tool_unavailable", "联网搜索不可用，跳过")
            return TaskSelection(reason="force_but_unavailable")
        await self._emit_decision_event(decision, trace, on_event, add_event)
        return TaskSelection(agent_call=decision.agent_call, reason=decision.reason)

    async def _emit_decision_event(
        self,
        decision: IntentDecision,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        add_event: Callable[..., Awaitable[AgentEvent]],
    ) -> None:
        if decision.trace_stage and decision.trace_label:
            await add_event(trace, on_event, decision.trace_stage, decision.trace_label)


def _planner_cache_scope(
    *,
    config: ResolvedAIConfig,
    route: AgentRoute | None,
    capabilities,
    user_id: str | None,
    request: ChatRequest,
) -> str:
    capability_key = ",".join(sorted(capability.name for capability in capabilities))
    return "|".join(
        [
            user_id or "anonymous",
            request.conversation_id or "no-conversation",
            config.model,
            "mode:llm",
            route.mode if route else "no-route",
            capability_key,
            f"rag:{int(request.use_rag)}",
            f"memory:{int(request.use_memory)}",
        ]
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.agent.config import ResolvedAIConfig
from app.agent.llm_planner import LLMCapabilityPlanner, PlannerDecision, capability_snapshot
from app.agent.plan_validator import PlanValidator
from app.agent.routing import AgentRoute
from app.agent.search.cache import get_planner_decision_cache
from app.agent.types import AgentEvent, AgentTrace, RuntimeAgentCall, RuntimeToolCall
from app.schemas.chat import ChatRequest


AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]

_GUARD_ERROR_CODES = {"imagery_not_found_or_forbidden", "owner_required"}


@dataclass(frozen=True)
class TaskSelection:
    tool_call: RuntimeToolCall | None = None
    agent_call: RuntimeAgentCall | None = None
    reason: str = "no_tool"
    planner_error_context: str | None = None


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
        capabilities = capability_snapshot()
        scope = _planner_cache_scope(
            config=config,
            route=route,
            capabilities=capabilities,
            user_id=user_id,
            request=request,
        )
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
            context = None
            if decision.action == "call":
                context = (
                    "能力规划已请求调用工具或子 Agent，但校验未通过，系统已禁止执行。\n"
                    f"- capability: {decision.capability}\n"
                    f"- error: {validated.validation_error}\n"
                    "- 回答时请说明本次没有执行外部能力，不要编造工具结果。"
                )
            return TaskSelection(reason=validated.validation_error, planner_error_context=context)

        if validated.action == "none":
            await add_event(
                trace,
                on_event,
                "planner_no_call",
                "规划结果无需调用能力",
                reason=validated.reason,
            )
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

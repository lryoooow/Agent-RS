from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from app.agent.capability_registry import get_capability, is_capability_enabled
from app.agent.llm_planner import PlannerDecision
from app.agent.routing import AgentRoute
from app.agent.tool_guards import validate_tool_access
from app.agent.types import RuntimeAgentCall, RuntimeToolCall


ValidatedAction = Literal["none", "call"]


@dataclass(frozen=True)
class ValidatedPlan:
    action: ValidatedAction
    capability_name: str | None = None
    capability_kind: Literal["tool", "agent"] | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    validation_error: str | None = None
    tool_call: RuntimeToolCall | None = None
    agent_call: RuntimeAgentCall | None = None


class PlanValidator:
    async def validate(
        self,
        decision: PlannerDecision,
        *,
        route: AgentRoute | None,
        user_id: str | None,
    ) -> ValidatedPlan:
        if decision.action != "call":
            return ValidatedPlan(action="none", reason=decision.reason or "planner_no_call")
        if not decision.capability:
            return self._invalid("missing_capability", decision)

        capability = get_capability(decision.capability)
        if capability is None:
            return self._invalid("unknown_capability", decision)
        if not is_capability_enabled(capability.name):
            return self._invalid("capability_disabled", decision)
        if route and capability.kind == "tool" and capability.name not in set(route.candidate_tools):
            return self._invalid("capability_not_allowed_by_route", decision)
        if route and capability.kind == "agent" and capability.name not in set(route.candidate_agents):
            return self._invalid("capability_not_allowed_by_route", decision)

        try:
            args_model = capability.argument_model.model_validate(decision.arguments or {})
        except ValidationError as exc:
            return self._invalid("invalid_arguments", decision, detail=str(exc))
        arguments = args_model.model_dump(exclude_none=True)

        guard_error = await validate_tool_access(capability.name, arguments, user_id)
        if guard_error:
            return self._invalid(guard_error, decision)

        if capability.kind == "tool":
            tool_call = RuntimeToolCall(name=capability.name, arguments=arguments, call_id=None)
            return ValidatedPlan(
                action="call",
                capability_name=capability.name,
                capability_kind="tool",
                arguments=arguments,
                reason=decision.reason,
                tool_call=tool_call,
            )
        agent_call = RuntimeAgentCall(name=capability.name, arguments=arguments, call_id=None)
        return ValidatedPlan(
            action="call",
            capability_name=capability.name,
            capability_kind="agent",
            arguments=arguments,
            reason=decision.reason,
            agent_call=agent_call,
        )

    def _invalid(
        self,
        error: str,
        decision: PlannerDecision,
        *,
        detail: str | None = None,
    ) -> ValidatedPlan:
        return ValidatedPlan(
            action="none",
            capability_name=decision.capability,
            arguments=decision.arguments or {},
            reason=decision.reason,
            validation_error=detail or error,
        )

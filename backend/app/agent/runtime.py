import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.agent.child import ToolChildAgent
from app.agent.capability_registry import is_capability_enabled
from app.agent.domain_agents import DomainToolAgent, domain_for_tool
from app.agent.search_agent import SearchChildAgent
from app.agent.tool_registry import list_tool_definitions
from app.agent.tool_selector import TaskSelector
from app.agent.types import AgentEvent, AgentTrace, RuntimeAgentCall, RuntimeToolCall, ToolRunResult
from app.agent.config import ResolvedAIConfig
from app.agent.prompting.scenarios import (
    latest_user_text,
    tool_final_label,
)
from app.agent.request_builder import (
    ProviderRequestContext,
    build_provider_request_context,
)
from app.agent.routing import AgentRoute, build_agent_route
from app.schemas.chat import ChatRequest, GeospatialResult, ToolResult
from app.core.settings import get_settings

logger = logging.getLogger(__name__)

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]


@dataclass(frozen=True)
class AgentPlanResult:
    response: Any | None
    final_context: ProviderRequestContext
    trace: AgentTrace
    used_capability: bool = False
    used_tool: bool = False
    dispatch_kind: str | None = None
    geospatial_result: GeospatialResult | None = None
    tool_result: ToolResult | None = None


class AgentRuntime:
    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def tools_available(self) -> bool:
        return True

    def trace(self) -> AgentTrace:
        return AgentTrace(enabled=self.tools_available)

    def tool_definitions(self) -> list[dict[str, Any]]:
        return list_tool_definitions()

    async def complete(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        initial_context: ProviderRequestContext,
        user_id: str | None,
        route: AgentRoute | None = None,
    ) -> AgentPlanResult:
        trace = self.trace()
        plan = await self.plan(
            client=client,
            config=config,
            request=request,
            initial_context=initial_context,
            user_id=user_id,
            trace=trace,
            route=route,
        )
        final_response = await self._create_completion(
            client=client,
            config=config,
            messages=plan.final_context.messages,
            stream=False,
        )
        return AgentPlanResult(
            response=final_response,
            final_context=plan.final_context,
            trace=plan.trace,
            used_capability=plan.used_capability,
            used_tool=plan.used_tool,
            dispatch_kind=plan.dispatch_kind,
            geospatial_result=plan.geospatial_result,
            tool_result=plan.tool_result,
        )

    async def plan_stream(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        initial_context: ProviderRequestContext,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
        route: AgentRoute | None = None,
    ) -> AgentPlanResult:
        return await self.plan(
            client=client,
            config=config,
            request=request,
            initial_context=initial_context,
            user_id=user_id,
            trace=trace,
            on_event=on_event,
            route=route,
        )

    async def plan(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        initial_context: ProviderRequestContext,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
        route: AgentRoute | None = None,
    ) -> AgentPlanResult:
        await self._add_event(
            trace,
            on_event,
            "context_assembled",
            "上下文已装配",
            retrieved_chunks=initial_context.retrieved_chunks,
            rag_trace=initial_context.rag_trace,
        )

        tools = self.tool_definitions()
        if not tools and not is_capability_enabled("web_search"):
            await self._add_event(trace, on_event, "tool_unavailable", "工具未配置，跳过工具调用")
            return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

        query = latest_user_text(request.messages)
        route = route or build_agent_route(query, request)

        selection = await TaskSelector().select(
            client=client,
            config=config,
            request=request,
            query=query,
            user_id=user_id,
            trace=trace,
            on_event=on_event,
            add_event=self._add_event,
            route=route,
        )
        if selection.tool_call is None and selection.agent_call is None:
            if selection.planner_error_context:
                final_context = await build_provider_request_context(
                    request,
                    user_id=user_id,
                    tool_context=selection.planner_error_context,
                    retrieved_context=initial_context.retrieved_context,
                )
                await self._add_event(
                    trace,
                    on_event,
                    "final_answering",
                    "能力规划未执行，正在生成直接回答",
                    tool_context_chars=len(selection.planner_error_context),
                    dispatch_kind="planner_error",
                )
                return AgentPlanResult(response=None, final_context=final_context, trace=trace)
            return AgentPlanResult(response=None, final_context=initial_context, trace=trace)

        if selection.tool_call is not None:
            tool_result = await self.run_tool_call(
                selection.tool_call, trace=trace, on_event=on_event, user_id=user_id,
            )
            dispatch_name = selection.tool_call.name
            dispatch_kind = "tool"
        else:
            tool_result = await self.run_agent_call(
                selection.agent_call, trace=trace, on_event=on_event,
            )
            dispatch_name = selection.agent_call.name
            dispatch_kind = "agent"
        final_context = await build_provider_request_context(
            request,
            user_id=user_id,
            tool_context=tool_result.tool_context,
            retrieved_context=initial_context.retrieved_context,
        )
        await self._add_event(
            trace,
            on_event,
            "final_answering",
            tool_final_label(dispatch_name),
            tool_context_chars=len(tool_result.tool_context),
            dispatch_kind=dispatch_kind,
        )
        return AgentPlanResult(
            response=None,
            final_context=final_context,
            trace=trace,
            used_capability=True,
            used_tool=dispatch_kind == "tool",
            dispatch_kind=dispatch_kind,
            geospatial_result=tool_result.geospatial_result,
            tool_result=tool_result.tool_result,
        )

    async def run_tool_call(
        self,
        tool_call: RuntimeToolCall,
        *,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
        user_id: str | None = None,
    ) -> ToolRunResult:
        # 按领域归属派发到对应领域子 agent；未登记的工具回退通用执行器，保证不退化。
        domain = domain_for_tool(tool_call.name)
        if domain is not None:
            return await DomainToolAgent(domain).run(
                tool_call,
                user_id=user_id,
                trace=trace,
                on_event=on_event,
            )
        return await ToolChildAgent().run(
            tool_call,
            user_id=user_id,
            trace=trace,
            on_event=on_event,
        )

    async def run_agent_call(
        self,
        agent_call: RuntimeAgentCall,
        *,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
    ) -> ToolRunResult:
        return await SearchChildAgent().run(
            agent_call,
            trace=trace,
            on_event=on_event,
        )

    async def _add_event(
        self,
        trace: AgentTrace,
        on_event: AgentEventCallback | None,
        stage: str,
        label: str,
        **metadata: Any,
    ) -> AgentEvent:
        event = trace.add(stage, label, **metadata)
        if on_event:
            await on_event(event)
        return event

    async def _create_completion(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        messages: list[dict[str, str]],
        stream: bool,
        **kwargs: Any,
    ) -> Any:
        return await client.chat.completions.create(
            model=config.model,
            messages=messages,
            stream=stream,
            extra_body={"enable_thinking": True, "thinking_budget": self.settings.ai_thinking_budget},
            **kwargs,
        )

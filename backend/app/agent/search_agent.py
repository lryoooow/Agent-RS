from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from app.agent.prompting.scenarios import tool_ready_label, tool_request_label
from app.agent.search.agent import run_web_search
from app.agent.search.schema import WebSearchArguments
from app.agent.types import AgentEvent, AgentTrace, RuntimeAgentCall, ToolRunResult
from app.core.settings import get_settings

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]
SEARCH_AGENT_NAME = "web_search"


class SearchAgentInput(WebSearchArguments):
    pass


class SearchChildAgent:
    def __init__(self, *, parent_run_id: str | None = None) -> None:
        self.parent_run_id = parent_run_id or uuid.uuid4().hex

    async def run(
        self,
        agent_call: RuntimeAgentCall,
        *,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
    ) -> ToolRunResult:
        settings = get_settings()
        child_run_id = uuid.uuid4().hex
        await self._add_event(
            trace, on_event, "tool_requested",
            tool_request_label(agent_call.name),
            tool_name=agent_call.name,
            query=agent_call.arguments.get("query"),
            reason=agent_call.arguments.get("reason"),
            agent_name="search_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="agent",
            dispatch_kind="agent",
        )

        if agent_call.name != SEARCH_AGENT_NAME:
            message = f"不允许调用子 Agent：{agent_call.name}"
            await self._add_event(
                trace, on_event, "tool_context_ready", message,
                agent_name="search_child_agent",
                requested_agent=agent_call.name,
                error="agent_unavailable",
                parent_run_id=self.parent_run_id,
                child_run_id=child_run_id,
                execution_kind="agent",
                dispatch_kind="agent",
            )
            return ToolRunResult(
                tool_context=f"子 Agent 未执行：{message}",
                error="agent_unavailable",
                metadata={"error_code": "agent_unavailable"},
            )

        try:
            args = SearchAgentInput.model_validate(agent_call.arguments)
        except ValidationError as exc:
            message = "搜索参数无效"
            await self._add_event(
                trace, on_event, "tool_context_ready", message,
                tool_name=agent_call.name, error=str(exc),
                agent_name="search_child_agent",
                parent_run_id=self.parent_run_id,
                child_run_id=child_run_id,
                execution_kind="agent",
                dispatch_kind="agent",
            )
            return ToolRunResult(
                tool_context=f"{message}，已跳过搜索。",
                error=str(exc),
                metadata={"error_code": "invalid_arguments"},
            )

        args = args.clamped(settings.agent_web_search_max_results)
        if len(args.query) > settings.agent_web_search_input_max_chars:
            message = "联网搜索 query 超过长度限制，已跳过搜索。"
            await self._add_event(
                trace, on_event, "tool_context_ready", message,
                tool_name=agent_call.name, error="query_too_long",
                agent_name="search_child_agent",
                parent_run_id=self.parent_run_id,
                child_run_id=child_run_id,
                execution_kind="agent",
                dispatch_kind="agent",
            )
            return ToolRunResult(
                tool_context=message,
                error="query 超过长度限制",
                metadata={"error_code": "query_too_long"},
            )

        await self._add_event(
            trace, on_event, "child_agent_running",
            f"正在执行搜索: {agent_call.name}",
            tool_name=agent_call.name,
            agent_name="search_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="agent",
            dispatch_kind="agent",
        )
        await self._add_event(
            trace, on_event, "tool_execution_started",
            "搜索执行已开始",
            tool_name=agent_call.name,
            agent_name="search_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="agent",
            dispatch_kind="agent",
        )

        try:
            result = await run_web_search(args)
        except Exception as exc:
            result = ToolRunResult(
                tool_context="搜索执行失败，已跳过搜索结果。",
                error=str(exc),
                metadata={"error_code": "search_runner_exception"},
            )

        await self._add_event(
            trace, on_event,
            "tool_execution_failed" if result.error else "tool_execution_completed",
            "搜索执行失败" if result.error else "搜索执行完成",
            tool_name=agent_call.name,
            agent_name="search_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="agent",
            dispatch_kind="agent",
            **result.metadata,
        )
        await self._add_event(
            trace, on_event, "tool_context_ready",
            tool_ready_label(agent_call.name),
            query=result.query,
            result_count=result.result_count,
            error=result.error,
            tool_context_chars=len(result.tool_context),
            tool_name=agent_call.name,
            agent_name="search_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="agent",
            dispatch_kind="agent",
            **result.metadata,
        )
        return result

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

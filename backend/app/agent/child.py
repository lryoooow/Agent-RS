from __future__ import annotations

import uuid
from typing import Any, Awaitable, Callable

from pydantic import ValidationError

from app.agent.prompting.scenarios import tool_ready_label, tool_request_label, tool_running_label
from app.agent.tool_guards import validate_tool_access
from app.agent.tool_registry import get_tool
from app.agent.types import AgentEvent, AgentTrace, RuntimeToolCall, ToolRunResult

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]


class ToolChildAgent:
    def __init__(self, *, parent_run_id: str | None = None) -> None:
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
        await self._add_event(
            trace,
            on_event,
            "tool_requested",
            tool_request_label(tool_call.name),
            tool_name=tool_call.name,
            query=tool_call.arguments.get("query"),
            reason=tool_call.arguments.get("reason"),
            agent_name="tool_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="tool",
            dispatch_kind="tool",
        )

        tool = get_tool(tool_call.name)
        if tool is None or not tool.is_enabled():
            message = f"不允许调用工具：{tool_call.name}"
            await self._add_event(
                trace,
                on_event,
                "tool_context_ready",
                message,
                tool_name=tool_call.name,
                error="tool_unavailable",
                agent_name="tool_child_agent",
                parent_run_id=self.parent_run_id,
                child_run_id=child_run_id,
                execution_kind="tool",
                dispatch_kind="tool",
            )
            return ToolRunResult(
                tool_context=f"工具未执行：{message}",
                error="tool_unavailable",
                metadata={"error_code": "tool_unavailable"},
            )

        try:
            args = tool.argument_model.model_validate(tool_call.arguments)
        except ValidationError as exc:
            message = "工具参数无效"
            await self._add_event(
                trace,
                on_event,
                "tool_context_ready",
                message,
                tool_name=tool_call.name,
                error=str(exc),
                agent_name="tool_child_agent",
                parent_run_id=self.parent_run_id,
                child_run_id=child_run_id,
                execution_kind="tool",
                dispatch_kind="tool",
            )
            return ToolRunResult(
                tool_context=f"{message}，已跳过执行。",
                error=str(exc),
                metadata={"error_code": "invalid_arguments"},
            )

        access_error = validate_tool_access(tool_call.name, args.model_dump(), user_id)
        if access_error:
            message = "工具访问被拒绝"
            await self._add_event(
                trace,
                on_event,
                "tool_context_ready",
                message,
                tool_name=tool_call.name,
                error=access_error,
                agent_name="tool_child_agent",
                parent_run_id=self.parent_run_id,
                child_run_id=child_run_id,
                execution_kind="tool",
                dispatch_kind="tool",
            )
            return ToolRunResult(
                tool_context=f"{message}：当前用户无权访问该资源。",
                error=access_error,
                metadata={"error_code": access_error},
            )

        await self._add_event(
            trace,
            on_event,
            "child_agent_running",
            tool_running_label(tool_call.name),
            tool_name=tool_call.name,
            agent_name="tool_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="tool",
            dispatch_kind="tool",
        )
        await self._add_event(
            trace,
            on_event,
            "tool_execution_started",
            tool_running_label(tool_call.name),
            tool_name=tool_call.name,
            agent_name="tool_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="tool",
            dispatch_kind="tool",
        )
        try:
            result = await tool.runner(args)
        except Exception as exc:
            result = ToolRunResult(
                tool_context="工具执行失败，已跳过该工具结果。",
                error=str(exc),
                metadata={"error_code": "tool_runner_exception"},
            )

        if result.metadata.get("fallback_used"):
            await self._add_event(
                trace,
                on_event,
                "tool_fallback_used",
                "工具使用了本地回退",
                tool_name=tool_call.name,
                agent_name="tool_child_agent",
                parent_run_id=self.parent_run_id,
                child_run_id=child_run_id,
                execution_kind="tool",
                dispatch_kind="tool",
                **result.metadata,
            )
        await self._add_event(
            trace,
            on_event,
            "tool_execution_failed" if result.error else "tool_execution_completed",
            "工具执行失败" if result.error else "工具执行完成",
            tool_name=tool_call.name,
            agent_name="tool_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="tool",
            dispatch_kind="tool",
            **result.metadata,
        )
        if result.geospatial_result:
            result_type = (
                result.geospatial_result.get("type")
                if isinstance(result.geospatial_result, dict)
                else result.geospatial_result.type
            )
            await self._add_event(
                trace,
                on_event,
                "geospatial_result_ready",
                "地图图层结果已生成",
                tool_name=tool_call.name,
                result_type=result_type,
                agent_name="tool_child_agent",
                parent_run_id=self.parent_run_id,
                child_run_id=child_run_id,
                execution_kind="tool",
                dispatch_kind="tool",
            )
        await self._add_event(
            trace,
            on_event,
            "tool_context_ready",
            tool_ready_label(tool_call.name),
            query=result.query,
            result_count=result.result_count,
            error=result.error,
            tool_context_chars=len(result.tool_context),
            tool_name=tool_call.name,
            agent_name="tool_child_agent",
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="tool",
            dispatch_kind="tool",
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

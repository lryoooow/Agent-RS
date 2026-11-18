from contextvars import ContextVar

from langchain.agents.middleware import AgentMiddleware, ClearToolUsesEdit, ContextEditingMiddleware
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from pydantic import ValidationError

from app.agent.engine.tools import RemoteSensingTool, ToolExecutionFailure
from app.agent.engine.turn_context import current_turn_state
from app.core.settings import get_settings

_call = ContextVar("langgraph_tool_call_id", default=None)


class ToolGuards(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        from app.mcp.hub import get_mcp_hub
        active = get_mcp_hub().active_tools()
        return await handler(request.override(tools=[tool for tool in request.tools if tool.name in active]))

    async def awrap_tool_call(self, request, handler):
        call = request.tool_call
        token = _call.set(call["id"])
        try:
            return await handler(request)
        except (ToolExecutionFailure, ValidationError, ValueError) as exc:
            return ToolMessage(content=str(exc)[:1500], tool_call_id=call["id"], name=call["name"], status="error")
        finally:
            _call.reset(token)


def middleware():
    return [ToolGuards(), ContextEditingMiddleware(edits=[
        ClearToolUsesEdit(trigger=max(1, get_settings().context_max_total_chars), keep=3)])]


def as_langchain_tool(tool, cancellation):
    guarded = RemoteSensingTool(tool)
    async def execute(**arguments):
        return await guarded.run_json(arguments, cancellation, call_id=_call.get())
    return StructuredTool.from_function(name=tool.name, description=tool.definition["function"]["description"],
                                       args_schema=tool.argument_model, coroutine=execute)

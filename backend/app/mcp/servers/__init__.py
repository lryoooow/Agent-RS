"""MCP services backed by the platform's guarded tool registry."""
import asyncio

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_context
from fastmcp.tools import Tool, ToolResult

from app.agent.engine import invoke_mcp_tool
from app.agent.tool_registry import BUILTIN_TOOLS
from app.mcp.progress import current_progress, progress_scope


class GuardedTool(Tool):
    async def run(self, arguments: dict) -> ToolResult:
        context = get_context()
        pending = asyncio.Queue(maxsize=128)
        previous = current_progress()

        def receive(update):
            if previous:
                previous(update)
            if not pending.full():
                pending.put_nowait(update)

        async def forward():
            while (update := await pending.get()) is not None:
                await context.report_progress(update.progress, update.total, update.message)

        sender = asyncio.create_task(forward())
        try:
            with progress_scope(receive):
                result = await invoke_mcp_tool(self.name, arguments)
            if pending.full():
                pending.get_nowait()
            pending.put_nowait(None)
            await sender
            return ToolResult(content=result)
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)


def add_guarded_tool(server, tool):
    read_only = tool.name in {"raster_inspect", "search_imagery", "web_search", "ontology_check"}
    server.add_tool(GuardedTool(name=tool.name, description=tool.definition["function"]["description"],
        parameters=tool.argument_model.model_json_schema(), annotations={
            "readOnlyHint": read_only, "idempotentHint": tool.recovery_policy == "idempotent",
            "destructiveHint": False, "openWorldHint": tool.name in {"web_search", "search_imagery", "fetch_scene"}}))


def build_domain(name: str, names) -> FastMCP:
    server = FastMCP(name)
    for key in names:
        add_guarded_tool(server, BUILTIN_TOOLS[key])
    return server

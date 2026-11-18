"""Expose the existing Docker operator implementation through FastMCP."""
import asyncio
import hmac
import os
from pathlib import Path
import re
import threading

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_context
from fastmcp.tools import Tool
try:
    from fastmcp.tools import ToolResult
except ImportError:  # FastMCP 2 in Python 3.10 vendor images
    from fastmcp.tools.tool import ToolResult
from starlette.responses import PlainTextResponse
import mcp_server as operator

server = FastMCP(operator.SERVER_NAME)
HTTP = os.environ.get("MCP_TRANSPORT", "stdio") == "streamable_http"


def validate_paths(args):
    source = Path(args["input_path"]).resolve(strict=True)
    jobs = Path("/jobs").resolve()
    if (source.name != "source.tif" or source.parent.name != "input" or source.parents[2] != jobs or
            not re.fullmatch(r"job-[a-zA-Z0-9_-]+", source.parents[1].name)):
        raise ValueError("invalid staged input")
    job = source.parents[1]
    for key, expected in (("output_dir", job / "output"), ("quality_path", job / "input" / "quality.tif")):
        if key in args and Path(args[key]).resolve(strict=True) != expected:
            raise ValueError("invalid staged job path")


class OperatorTool(Tool):
    async def run(self, arguments):
        if HTTP:
            validate_paths(arguments)
        context = get_context()
        await context.report_progress(0, 100, "已开始读取影像")
        loop = asyncio.get_running_loop()
        cancelled = threading.Event()

        def progress(value, total, message):
            if cancelled.is_set():
                raise RuntimeError("operator cancelled")
            future = asyncio.run_coroutine_threadsafe(context.report_progress(value, total, message), loop)
            future.result(timeout=10)

        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                   "params": {"name": self.name, "arguments": arguments, "_meta": {"agent-rs/compact-result": True}}}
        options = {"progress": progress} if self.name == "detect_objects" else {}
        work = asyncio.create_task(asyncio.to_thread(operator.handle, request, **options))
        try:
            reply = await asyncio.shield(work)
        except asyncio.CancelledError:
            cancelled.set()
            await asyncio.gather(work, return_exceptions=True)
            raise
        result = reply.get("result", {})
        if "error" in reply or result.get("isError"):
            raise ValueError(next((v["text"] for v in result.get("content", []) if v.get("type") == "text"), "operator failed"))
        await context.report_progress(100, 100, "算子结果已写入")
        return ToolResult(content=result["content"], structured_content=result["structuredContent"])


for definition in operator.TOOL_DEFINITIONS:
    name = definition["name"]
    server.add_tool(OperatorTool(name=name, description=definition["description"],
        parameters=definition["inputSchema"], annotations={"readOnlyHint":name == "raster_inspect",
        "idempotentHint":name == "raster_inspect", "destructiveHint":False, "openWorldHint":False}))


class BearerGate:
    def __init__(self, app, secret):
        self.app, self.expected = app, ("Bearer " + secret).encode()

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and not hmac.compare_digest(dict(scope["headers"]).get(b"authorization", b""), self.expected):
            await PlainTextResponse("Unauthorized", status_code=401)(scope, receive, send)
            return
        await self.app(scope, receive, send)


if __name__ == "__main__":
    if HTTP:
        import uvicorn
        token = os.environ.get("MCP_OPERATOR_TOKEN")
        if not token:
            raise SystemExit("MCP_OPERATOR_TOKEN is required for HTTP")
        uvicorn.run(BearerGate(server.http_app(path="/mcp"), token), host="0.0.0.0", port=8000)
    else:
        server.run(transport="stdio", show_banner=False)

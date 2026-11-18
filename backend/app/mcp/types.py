"""Shared MCP wire types and bounds for both operator transports."""
from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, SecretStr

MAX_FRAME_BYTES = 4 * 1024 * 1024
LEGACY_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
STATELESS_VERSION = "2026-07-28"


class MCPCallError(Exception):
    """Transport or tool failed before returning a usable result."""


class MCPMethodUnavailable(MCPCallError):
    """The peer explicitly reported JSON-RPC Method not found."""


class MCPResourceContent(BaseModel):
    uri: str
    mimeType: str | None = None
    text: str | None = None
    blob: str | None = None


class MCPPromptTemplate(BaseModel):
    name: str
    description: str = ""
    arguments: list[dict] = Field(default_factory=list)


class MCPDiscoveredTool(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=8192)
    inputSchema: dict
    outputSchema: dict | None = None
    annotations: dict | None = None


class MCPServerSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z][a-z0-9_]{0,30}$")
    name: str = Field(min_length=1, max_length=120)
    transport: Literal["streamable_http", "stdio"] = "streamable_http"
    endpoint_url: str | None = Field(default=None, max_length=2048)
    auth_bearer_token: SecretStr | None = None
    stdio_command: list[str] | None = Field(default=None, min_length=1, max_length=32)
    enabled: bool = True
    timeout_seconds: float = Field(default=30, gt=0, le=600, allow_inf_nan=False)


class MCPServerHealth(BaseModel):
    status: Literal["healthy", "disabled", "unavailable", "open"]
    tool_count: int = 0


@dataclass(frozen=True)
class MCPProgressUpdate:
    progress: float
    total: float | None = None
    message: str = ""


ProgressCallback = Callable[[MCPProgressUpdate], None]


@dataclass
class Request:
    method: str
    params: dict
    on_progress: ProgressCallback | None = None
    token: str = field(default_factory=lambda: uuid4().hex)
    sent: bool = False
    collection: str | None = None
    request_id: int = 2

    def frame(self, request_id: int | str | None = None) -> dict:
        params = dict(self.params)
        if self.method == "tools/call" and params.get("name") == "ocr_recognize":
            params["_meta"] = {**params.get("_meta", {}), "agent-rs/compact-result": True}
        if self.on_progress:
            params["_meta"] = {**params.get("_meta", {}), "progressToken": self.token}
        return {"jsonrpc": "2.0", "id": self.request_id if request_id is None else request_id, "method": self.method, "params": params}

    def notification(self, frame: dict) -> None:
        params = frame.get("params")
        if frame.get("method") != "notifications/progress" or not self.on_progress or not isinstance(params, dict):
            return
        if params.get("progressToken") != self.token:
            return
        progress, total = params.get("progress"), params.get("total")
        def valid(value):
            return type(value) in (int, float) and 0 <= value <= sys.float_info.max
        if not valid(progress) or (total is not None and (not valid(total) or total < progress)):
            return
        self.on_progress(MCPProgressUpdate(progress, total, str(params.get("message") or "")[:512]))


def response(frame: dict, request_id: int | str, method: str) -> dict | None:
    if not isinstance(frame, dict) or frame.get("jsonrpc") != "2.0":
        raise MCPCallError("invalid JSON-RPC message")
    if "id" not in frame and isinstance(frame.get("method"), str):
        return None
    if type(frame.get("id")) is not type(request_id) or frame["id"] != request_id or "method" in frame:
        raise MCPCallError(f"unexpected response id for {method}")
    if "error" in frame:
        error = frame["error"]
        message = str(error.get("message", ""))[:1024] if isinstance(error, dict) else "protocol error"
        if isinstance(error, dict) and error.get("code") == -32601:
            raise MCPMethodUnavailable(f"{method} is not available")
        raise MCPCallError(f"{method} failed: {message}")
    result = frame.get("result")
    if not isinstance(result, dict):
        raise MCPCallError(f"invalid result for {method}")
    return result


class MCPPrimitives:
    async def request(self, request: Request) -> dict:
        raise NotImplementedError

    async def _list(self, key: str) -> list[dict]:
        items, seen, params = [], set(), {}
        for _ in range(64):
            page = await self.request(Request(f"{key}/list", params))
            entries = page.get(key)
            if not isinstance(entries, list) or len(entries) + len(items) > 2048 or not all(isinstance(e, dict) for e in entries):
                raise MCPCallError(f"invalid {key} list")
            items.extend(entries)
            cursor = page.get("nextCursor")
            if cursor is None:
                return items
            if not isinstance(cursor, str) or cursor in seen:
                raise MCPCallError("invalid MCP pagination cursor")
            seen.add(cursor)
            params = {"cursor": cursor}
        raise MCPCallError("too many MCP pages")

    async def list_tools(self):
        return await self._list("tools")

    async def list_resources(self):
        return await self._list("resources")

    async def read_resource(self, uri: str):
        return await self.request(Request("resources/read", {"uri": uri}))

    async def list_prompts(self):
        return await self._list("prompts")

    async def get_prompt(self, name: str, arguments: dict | None = None):
        return await self.request(Request("prompts/get", {"name": name, "arguments": arguments or {}}))

    async def call_tool_result(self, tool_name: str, arguments: dict, *, on_progress: ProgressCallback | None = None):
        result = await self.request(Request("tools/call", {"name": tool_name, "arguments": arguments}, on_progress))
        if result.get("isError"):
            texts = [item.get("text") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"]
            raise MCPCallError(str(next(iter(texts), "tool returned isError without message"))[:2048])
        return result

    async def call_tool(self, tool_name: str, arguments: dict, *, on_progress: ProgressCallback | None = None):
        result = await self.call_tool_result(tool_name, arguments, on_progress=on_progress)
        data = result.get("structuredContent")
        if data is None:
            content = result.get("content") or []
            if len(content) == 1 and isinstance(content[0], dict) and content[0].get("type") == "text":
                try:
                    data = json.loads(content[0]["text"])
                except (KeyError, TypeError, ValueError):
                    pass
        if not isinstance(data, dict):
            raise MCPCallError("missing structuredContent in tool response")
        return data

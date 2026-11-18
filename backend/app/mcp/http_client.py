"""MCP over Streamable HTTP, with a connection-bound external host policy."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx2
from fastmcp import Client
from mcp.shared.exceptions import MCPError as SDKError
from fastmcp.client.transports import StreamableHttpTransport

from app.mcp.types import MAX_FRAME_BYTES, MCPCallError, MCPMethodUnavailable, MCPPrimitives, Request


def validate_endpoint(url: str, allowed_hosts: set[str], *, operator: bool = False) -> str:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid MCP endpoint") from exc
    schemes = {"http", "https"} if operator else {"https"}
    if (not host or parts.scheme not in schemes or host not in allowed_hosts or
            parts.username is not None or parts.password is not None or parts.fragment or parts.query or
            any(c.isspace() or ord(c) < 32 for c in url) or "\\" in url or port == 0):
        raise ValueError("MCP endpoint must use an allowed host and transport")
    return host


def resolve_endpoint(host: str, port: int, *, operator: bool) -> str:
    try:
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [ipaddress.ip_address(item[4][0]) for item in records]
    except (OSError, ValueError) as exc:
        raise ValueError("MCP endpoint cannot be resolved") from exc
    if not addresses or (not operator and any(not ip.is_global or ip.is_multicast for ip in addresses)):
        raise ValueError("MCP external endpoint resolves to a non-public address")
    return str(addresses[0])


class BoundedJSONBody(httpx2.AsyncByteStream):
    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        size = 0
        async for chunk in self.stream:
            size += len(chunk)
            if size > MAX_FRAME_BYTES:
                raise MCPCallError("MCP JSON response exceeds frame limit")
            yield chunk

    async def aclose(self):
        await self.stream.aclose()


class EndpointTransport(httpx2.AsyncHTTPTransport):
    def __init__(self, endpoint: str, allowed_hosts: set[str], *, operator: bool = False):
        super().__init__(trust_env=False)
        self.host = validate_endpoint(endpoint, allowed_hosts, operator=operator)
        self.endpoint = httpx2.URL(endpoint)
        self.operator = operator

    async def handle_async_request(self, request):
        if request.url != self.endpoint:
            raise ValueError("MCP request must use its registered endpoint")
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        address = await asyncio.to_thread(resolve_endpoint, self.host, port, operator=self.operator)
        # Connect to the exact address checked above, retaining the original Host and TLS identity.
        wire = httpx2.Request(request.method, request.url.copy_with(host=address), headers=request.headers,
                              stream=request.stream, extensions={**request.extensions, "sni_hostname": self.host})
        wire.headers["Accept-Encoding"] = "identity"
        result = await super().handle_async_request(wire)
        if result.headers.get("content-encoding", "identity").lower() != "identity":
            await result.aclose()
            raise MCPCallError("unsupported MCP response encoding")
        if "application/json" in result.headers.get("content-type", "").lower():
            result.stream = BoundedJSONBody(result.stream)
        if 300 <= result.status_code < 400:
            await result.aclose()
            raise ValueError("MCP redirects are disabled")
        return result


class StreamableHTTPMCPClient(MCPPrimitives):
    def __init__(self, endpoint_url: str, *, allowed_hosts: set[str], timeout_seconds: float = 30,
                 bearer_token: str | None = None, operator: bool = False, on_list_changed=None):
        validate_endpoint(endpoint_url, allowed_hosts, operator=operator)
        self.endpoint = httpx2.URL(endpoint_url)
        self.operator = operator
        self.timeout_seconds = timeout_seconds
        self.on_list_changed = on_list_changed

        def factory(**kwargs):
            kwargs.update(follow_redirects=False, trust_env=False,
                          transport=EndpointTransport(endpoint_url, allowed_hosts, operator=operator))
            return httpx2.AsyncClient(**kwargs)

        async def message_handler(message):
            if on_list_changed and getattr(message, "method", "") == "notifications/tools/list_changed":
                on_list_changed()

        transport = StreamableHttpTransport(endpoint_url, auth=bearer_token, httpx_client_factory=factory,
                                             max_sse_event_size=MAX_FRAME_BYTES)
        # The SDK negotiates per-request 2026 semantics or a legacy session, handles both
        # JSON and SSE, and correlates progress/cancellation to the outstanding request.
        self.client = Client(transport, timeout=timeout_seconds, init_timeout=timeout_seconds,
                             mode="auto", message_handler=message_handler)

    async def _list(self, key):
        # A legacy server may bind cursors to its session.
        try:
            async with asyncio.timeout(self.timeout_seconds), self.client:
                return await super()._list(key)
        except (MCPCallError, TimeoutError, asyncio.CancelledError):
            raise
        except Exception as exc:
            raise MCPCallError(f"{key}/list failed ({type(exc).__name__})") from exc

    async def validate_address(self):
        port = self.endpoint.port or (443 if self.endpoint.scheme == "https" else 80)
        return await asyncio.to_thread(resolve_endpoint, self.endpoint.host, port, operator=self.operator)

    async def watch(self):
        """Hold a single SDK connection, including the separate change stream on modern servers."""
        from mcp.client.subscriptions import listen
        async with self.client as client:
            capabilities = client.server_capabilities
            tools = getattr(capabilities, "tools", None)
            if not getattr(tools, "list_changed", False):
                return
            if client.protocol_version == "2026-07-28":
                async with listen(client.session, tools_list_changed=True) as subscription:
                    async for event in subscription:
                        if self.on_list_changed:
                            self.on_list_changed()
            else:
                # The legacy HTTP session delivers list changes via its GET stream.
                await asyncio.Event().wait()

    async def request(self, request: Request) -> dict:
        async def progress(value, total, message):
            request.notification({"method": "notifications/progress", "params": {
                "progressToken": request.token, "progress": value, "total": total, "message": message}})

        try:
            async with asyncio.timeout(self.timeout_seconds), self.client as client:
                method = {"tools/list": client.list_tools_mcp, "resources/list": client.list_resources_mcp,
                          "resources/read": client.read_resource_mcp, "prompts/list": client.list_prompts_mcp,
                          "prompts/get": client.get_prompt_mcp, "tools/call": client.call_tool_mcp}[request.method]
                params = dict(request.params)
                if request.method == "tools/call" and request.on_progress:
                    params["progress_handler"] = progress
                result = await method(**params)
                return result.model_dump(mode="json", by_alias=True, exclude_none=True)
        except (TimeoutError, asyncio.CancelledError):
            raise
        except SDKError as exc:
            if exc.code == -32601:
                raise MCPMethodUnavailable(f"{request.method} is not available") from exc
            raise MCPCallError(f"{request.method} failed (MCP {exc.code})") from exc
        except Exception as exc:
            # URLs, credentials, input arguments and server-controlled text stay out of logs.
            raise MCPCallError(f"{request.method} failed ({type(exc).__name__})") from exc

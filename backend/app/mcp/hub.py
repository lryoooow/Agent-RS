"""Process-local registry snapshots. A running invocation owns its original server handle."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.settings import get_settings
from app.db.repositories.mcp_servers import MCPServerRepository
from app.mcp.schema_compiler import compile_jsonschema_to_pydantic
from app.mcp.types import MCPCallError, MCPDiscoveredTool, MCPMethodUnavailable, MCPServerSpec

logger = logging.getLogger(__name__)
NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


@dataclass
class MountedServer:
    spec: MCPServerSpec
    client: object | None = None
    tools: dict = field(default_factory=dict)
    descriptions: list = field(default_factory=list)
    resources: list = field(default_factory=list)
    prompts: list = field(default_factory=list)
    failures: int = 0
    retry_at: float = 0
    trial: bool = False
    static: bool = False
    watcher: asyncio.Task | None = None
    revision: object | None = None

    def available(self):
        return self.spec.enabled and self.client is not None and time.monotonic() >= self.retry_at and not self.trial

    @property
    def status(self):
        if not self.spec.enabled:
            return "disabled"
        if self.client is None:
            return "unavailable"
        return "healthy" if self.available() else "open"

    async def invoke(self, name, args):
        from app.agent.types import ToolRunResult
        from app.mcp.progress import current_progress
        if not self.available():
            raise MCPCallError("外部 MCP 服务尚未就绪")
        if self.retry_at:
            self.trial = True
        try:
            client = self.client.for_invocation() if self.spec.transport == "stdio" else self.client
            result = await client.call_tool_result(name, args.model_dump(exclude_unset=True, mode="json"),
                                                        on_progress=current_progress())
        except TimeoutError:
            self.failures += 1
            if self.failures >= 3:
                self.retry_at = time.monotonic() + 60
            raise
        else:
            self.failures = 0
            self.retry_at = 0
        finally:
            self.trial = False
        # Remote content is evidence. Only the platform may create map artifacts or ontology facts.
        text = "\n".join(str(item.get("text", "")) for item in result.get("content", [])
                         if isinstance(item, dict) and item.get("type") == "text")
        if not text:
            text = json.dumps(result.get("structuredContent"), ensure_ascii=False)
        return ToolRunResult(tool_context=text[:get_settings().ai_context_max_tool_chars],
                             metadata={"mcp_server": self.spec.slug, "mcp_tool": name})


class MCPHub:
    def __init__(self, repository=None):
        self.repository = repository or MCPServerRepository()
        self.servers: dict[str, MountedServer] = {}
        self.builtins: dict = {}
        self.lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()
        self.refreshing: set[str] = set()

    def get_effective_registry(self):
        from app.agent.tool_registry import BUILTIN_TOOLS
        registry = dict(BUILTIN_TOOLS)
        if get_settings().mcp_hotplug_enabled:
            for server in self.servers.values():
                if server.available():
                    registry.update(server.tools)
        return registry

    def active_tools(self):
        from app.agent.engine import current_turn_state
        state = current_turn_state()
        return {name: tool for name, tool in self.get_effective_registry().items()
                if tool.is_enabled() and (not state or state.available(name))}

    def _client(self, server: MountedServer):
        spec = server.spec
        if spec.transport == "stdio":
            if not server.static or not spec.stdio_command or spec.endpoint_url or spec.auth_bearer_token:
                raise ValueError("stdio 只允许服务端静态配置")
            from app.mcp.client import StdioMCPClient
            return StdioMCPClient(command=spec.stdio_command, timeout_seconds=spec.timeout_seconds,
                                  client_name="agent-rs", client_version="1")
        if not spec.endpoint_url or spec.stdio_command:
            raise ValueError("HTTP 服务需要固定端点")
        from app.mcp.http_client import StreamableHTTPMCPClient
        hosts = {h.strip().lower() for h in get_settings().mcp_allowed_hosts.split(",") if h.strip()}
        return StreamableHTTPMCPClient(spec.endpoint_url, allowed_hosts=hosts, timeout_seconds=spec.timeout_seconds,
            bearer_token=spec.auth_bearer_token.get_secret_value() if spec.auth_bearer_token else None,
            on_list_changed=lambda: self._schedule_refresh(server))

    def _publish(self, slug, server):
        previous = self.servers.get(slug)
        if previous and previous.watcher:
            previous.watcher.cancel()
        if server is None:
            self.servers = {k:v for k,v in self.servers.items() if k != slug}
            return
        self.servers = {**self.servers, slug: server}
        if server.client and hasattr(server.client, "watch"):
            async def watch():
                while self.servers.get(slug) is server:
                    try:
                        await server.client.watch()
                        return
                    except Exception:
                        await asyncio.sleep(15)
            server.watcher = asyncio.create_task(watch())
            self.tasks.add(server.watcher)
            server.watcher.add_done_callback(self.tasks.discard)

    def _schedule_refresh(self, server):
        slug = server.spec.slug
        if self.servers.get(slug) is not server or slug in self.refreshing:
            return
        self.refreshing.add(slug)
        async def refresh():
            try:
                await self.set_enabled(slug, True, expected=server)
            except Exception:
                logger.warning("MCP schema refresh failed for %s", slug)
            finally:
                self.refreshing.discard(slug)
        task = asyncio.create_task(refresh())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def probe(self, spec, *, static=False):
        from app.agent.tool_registry import BUILTIN_TOOLS, RegisteredTool
        server = MountedServer(spec, static=static)
        if "__" in spec.slug:
            raise ValueError("服务标识不能包含命名空间分隔符")
        client = self._client(server)
        if hasattr(client, "validate_address"):
            await client.validate_address()
        if not spec.enabled:
            return server
        server.client = client
        raw = await client.list_tools()
        if len(raw) > 64:
            raise ValueError("服务公开的工具数量超过上限")
        for item in raw:
            tool = MCPDiscoveredTool.model_validate(item)
            name = f"ext_{spec.slug}__{tool.name}"
            if (not NAME.fullmatch(tool.name) or tool.name.startswith(("ontology_", "ext_")) or
                    len(name) > 64 or name in BUILTIN_TOOLS or name in server.tools):
                raise ValueError("MCP 工具名称无效或冲突")
            model = compile_jsonschema_to_pydantic(name, tool.inputSchema)
            resource_keys = {"imagery_id", "document_id"} & model.model_fields.keys()
            if len(resource_keys) > 1:
                raise ValueError("一个外部工具只能绑定一种平台资源")
            kind = {"imagery_id": "imagery", "document_id": "document"}.get(next(iter(resource_keys), ""), "none")
            async def run(args, original=tool.name):
                return await server.invoke(original, args)
            definition = {"type":"function","function":{"name":name, "description":tool.description,
                                                        "parameters":model.model_json_schema()}}
            server.tools[name] = RegisteredTool(name, definition, model, run, "main_agent", kind,
                                                 enabled=server.available, tags=("external_mcp",))
            server.descriptions.append(tool.model_dump(exclude_none=True))
        # Resources and prompts are optional capabilities, including for older Docker servers.
        for key in ("resources", "prompts"):
            try:
                setattr(server, key, await getattr(client, f"list_{key}")())
            except MCPMethodUnavailable:
                pass
        from app.agent.ontology.catalog import build_catalog
        candidate = {name: tool for name, tool in self.get_effective_registry().items()
                     if not name.startswith(f"ext_{spec.slug}__")}
        build_catalog({**candidate, **server.tools}, discover=True)
        return server

    async def register_external_server(self, spec, *, static=False, restore=False):
        if not get_settings().mcp_hotplug_enabled:
            raise ValueError("外部 MCP 扩展已关闭")
        async with self.lock:
            if spec.slug in self.servers:
                raise ValueError("MCP 服务标识已存在")
            server = await self.probe(spec, static=static)
            if not static and not restore:
                server.revision = await self.repository.save(spec, server.descriptions, server.status, create=True)
                if server.revision is None:
                    raise ValueError("MCP 服务标识已存在")
            self._publish(spec.slug, server)
            return server

    async def set_enabled(self, slug, enabled, *, expected=None):
        async with self.lock:
            if enabled and not get_settings().mcp_hotplug_enabled:
                raise ValueError("外部 MCP 扩展已关闭")
            previous = self.servers[slug]
            if expected is not None and previous is not expected:
                return previous
            spec = previous.spec.model_copy(update={"enabled": enabled})
            server = await self.probe(spec, static=previous.static) if enabled else MountedServer(spec, static=previous.static)
            if not previous.static:
                server.revision = await self.repository.save(spec, server.descriptions, server.status, create=False,
                                                             expected_revision=previous.revision)
            self._publish(slug, server)
            return server

    async def unregister_external_server(self, slug):
        async with self.lock:
            current = self.servers[slug]
            if current.static:
                raise ValueError("静态服务由服务端配置管理")
            await self.repository.delete(slug)
            self._publish(slug, None)

    async def read_ontology_context(self, session_id):
        from fastmcp import Client
        async with Client(self.builtins["ontology"]) as client:
            blocks = await client.read_resource(f"ontology://session/{session_id}/context")
            return blocks[0].text

    async def _reconcile(self):
        # Other API workers commit to the same table. Keep the last usable schema if
        # discovery fails, and retry when the next snapshot arrives.
        while True:
            await asyncio.sleep(5)
            try:
                revisions = await self.repository.revisions()
                known = {slug: s.revision for slug, s in self.servers.items() if not s.static}
                if revisions == known and all(s.client or not s.spec.enabled for s in self.servers.values()):
                    continue
                async with self.lock:
                    revisions = await self.repository.revisions()
                    configs = {c.slug:c for c in await self.repository.list()}
                    for slug, server in list(self.servers.items()):
                        if not server.static and slug not in configs:
                            self._publish(slug, None)
                    for slug, spec in configs.items():
                        previous = self.servers.get(slug)
                        if previous and (previous.static or (previous.revision == revisions.get(slug)
                                and (previous.client or not spec.enabled))):
                            continue
                        try:
                            fresh = await self.probe(spec) if spec.enabled else MountedServer(spec)
                        except Exception:
                            continue
                        fresh.revision = revisions.get(slug)
                        self._publish(slug, fresh)
            except Exception:
                logger.warning("MCP registry synchronization temporarily unavailable")

    async def initialize(self):
        from app.mcp.ontology_server import build_ontology_mcp
        from app.mcp.servers.raster_mcp import build_raster_mcp
        from app.mcp.servers.vision_mcp import build_vision_mcp
        from app.mcp.servers.platform_mcp import build_platform_mcp
        self.builtins = {"ontology": build_ontology_mcp(), "raster": build_raster_mcp(),
                         "vision": build_vision_mcp(), "platform": build_platform_mcp()}
        settings = get_settings()
        if not settings.mcp_hotplug_enabled:
            return
        configs = []
        if settings.mcp_static_servers_file:
            rows = json.loads(Path(settings.mcp_static_servers_file).read_text(encoding="utf-8"))
            configs.extend((MCPServerSpec.model_validate(row), True) for row in rows)
        revisions = {}
        if settings.database_enabled:
            revisions = await self.repository.revisions()
            configs.extend((spec, False) for spec in await self.repository.list())
        for spec, static in configs:
            try:
                mounted = await self.register_external_server(spec, static=static, restore=True)
                mounted.revision = revisions.get(spec.slug)
            except Exception:
                if spec.slug not in self.servers:
                    self.servers[spec.slug] = MountedServer(spec, static=static)
                logger.warning("MCP service unavailable at startup: %s", spec.slug)

        if settings.database_enabled:
            task = asyncio.create_task(self._reconcile())
            self.tasks.add(task)
            task.add_done_callback(self.tasks.discard)

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.servers.clear()
        self.builtins.clear()
        self.refreshing.clear()


_hub = MCPHub()


def get_mcp_hub():
    return _hub


async def init_mcp_hub():
    await _hub.initialize()


async def close_mcp_hub():
    await _hub.close()

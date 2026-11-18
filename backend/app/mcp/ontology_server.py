from __future__ import annotations

import asyncio
from dataclasses import asdict
import json
from weakref import WeakKeyDictionary

import mcp.types as wire
from mcp.server.subscriptions import InMemorySubscriptionBus, ListenHandler, ResourceUpdated

from fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from app.agent.engine import current_turn_state
from app.agent.ontology.catalog import build_catalog
from app.agent.ontology.state import current_session
from app.agent.tool_registry import RegisteredTool, effective_registry
from app.agent.types import ToolRunResult
from app.auth import peek_current_user_id


def _session(session_id):
    turn, ontology = current_turn_state(), current_session()
    if (turn is None or turn.session_id != session_id or ontology is None or not ontology.user_id or
            ontology.user_id != peek_current_user_id()):
        raise ValueError("当前回合无权读取该图谱会话")
    return turn, ontology


def _routes(session, name=None, arguments=None):
    enabled = set(effective_registry()) if name is None else {name}
    arguments = arguments or {}
    identity = arguments.get("imagery_id") or arguments.get("document_id")
    return [asdict(route) for e in session.entities
            if not identity or identity in (e.get("id"), e.get("imagery_id"))
            for route in session.router.downstream(e, request=session.request, arguments=arguments, enabled=enabled)]


class CheckArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    tool_name: str
    arguments: dict = Field(default_factory=dict)


class ObserveArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    invocation_index: int = Field(ge=0)


async def _check(args):
    _, session = _session(args.session_id)
    if args.tool_name not in effective_registry():
        raise ValueError("未知工具")
    reason = session.reject(args.tool_name, args.arguments)
    data = {"blocked_reason": reason, "routes": _routes(session, args.tool_name, args.arguments)}
    return ToolRunResult(tool_context=json.dumps(data, ensure_ascii=False))


async def _observed(args):
    turn, session = _session(args.session_id)
    if args.invocation_index >= len(turn.invocations):
        raise ValueError("未找到该回合的执行记录")
    invocation = turn.invocations[args.invocation_index]
    if invocation.result.error:
        raise ValueError("失败调用不能生成事实")
    # The shared execution pipeline has already observed this verified result.
    return ToolRunResult(tool_context=session.context({invocation.name}))


def _tool(name, description, model, runner):
    return RegisteredTool(name, {"function": {"name":name, "description":description,
                          "parameters":model.model_json_schema()}}, model, runner, "main_agent", "none")


ONTOLOGY_TOOLS = {
    "ontology_check": _tool("ontology_check", "核实当前回合工具所需的证据与前置条件", CheckArguments, _check),
    "ontology_observe": _tool("ontology_observe", "查看真实成功调用已产生的图谱事实", ObserveArguments, _observed),
}


def _attach_resource_subscriptions(server):
    # The in-process SDK server receives the trusted turn context from its host.
    # Each subscription is checked at registration and bound to that turn's facts.
    bus = InMemorySubscriptionBus()
    listen = ListenHandler(bus)
    legacy = WeakKeyDictionary()

    def authorize(requested):
        turn = current_turn_state()
        if turn is None:
            raise ValueError("订阅需要已鉴权的回合")
        _, ontology = _session(turn.session_id)
        uris = {f"ontology://session/{turn.session_id}/{kind}" for kind in ("context", "routes")}
        if not requested or not set(requested) <= uris:
            raise ValueError("只能订阅当前回合的图谱资源")

        async def notify():
            for uri in sorted(uris):
                await bus.publish(ResourceUpdated(uri))
                for connection, subscriptions in list(legacy.items()):
                    if uri in subscriptions:
                        try:
                            await asyncio.wait_for(connection.send_resource_updated(uri), timeout=1)
                        except Exception:
                            legacy.pop(connection, None)
        ontology.notify_observers = notify

    async def listen_scoped(ctx, params):
        authorize(params.notifications.resource_subscriptions or [])
        return await listen(ctx, params)

    async def subscribe(ctx, params):
        uri = str(params.uri)
        authorize([uri])
        # SDK 2 supplies a new low-level session proxy per request. Subscriptions
        # belong to its underlying transport connection until unsubscribe or disconnect.
        legacy.setdefault(ctx.session._connection, set()).add(uri)
        return wire.EmptyResult()

    async def unsubscribe(ctx, params):
        uri = str(params.uri)
        authorize([uri])
        legacy.get(ctx.session._connection, set()).discard(uri)
        return wire.EmptyResult()

    protocol = server._mcp_server
    protocol.add_request_handler("subscriptions/listen", wire.SubscriptionsListenRequestParams, listen_scoped)
    protocol.add_request_handler("resources/subscribe", wire.SubscribeRequestParams, subscribe)
    protocol.add_request_handler("resources/unsubscribe", wire.UnsubscribeRequestParams, unsubscribe)


def build_ontology_mcp():
    from app.mcp.servers import add_guarded_tool
    server = FastMCP("Agent-RS Ontology")
    _attach_resource_subscriptions(server)

    @server.resource("ontology://schema/catalog", mime_type="application/json")
    def catalog() -> dict:
        schema, _, revision = build_catalog()
        return {"revision": revision, "schema": schema.model_dump()}

    @server.resource("ontology://session/{session_id}/routes", mime_type="application/json")
    def routes(session_id: str) -> list:
        _, session = _session(session_id)
        return _routes(session)

    @server.resource("ontology://session/{session_id}/context", mime_type="text/plain")
    def context(session_id: str) -> str:
        _, session = _session(session_id)
        from app.mcp.hub import get_mcp_hub
        return session.context(set(get_mcp_hub().active_tools()))

    for tool in ONTOLOGY_TOOLS.values():
        add_guarded_tool(server, tool)
    return server

# Agent-RS Agent and Tool Architecture

## Current Boundary

Agent-RS now separates the runtime into explicit responsibilities:

- `AIService`: prepares config, persistence, route, provider context, and provider client.
- `AgentRuntime`: parent orchestration shell. It assembles trace, asks the selector for a task decision, delegates execution, and builds the final answer context.
- `TaskSelector`: the only place that selects current tool calls or child-agent calls. NDVI intent, web-search classifier, decision cache, and planning-model fallback live here.
- `ToolChildAgent`: deterministic tool execution lifecycle. It validates arguments, runs access guards, executes the registered runner, catches runner exceptions, and emits trace events.
- `SearchChildAgent`: search child-agent lifecycle. It validates search input, runs search, catches search exceptions, and emits trace events.

Remote-sensing tools are deterministic MCP Docker tools. They are not child agents.

Web search is a child agent. It is not registered as a tool. Its search implementation lives under `backend/app/agent/search/`. It currently has no internal LLM loop; if query rewriting, multi-step search, or source self-checking is needed later, that logic belongs inside `SearchChildAgent`.

## Tool Contract

Every deterministic tool must be registered in `backend/app/agent/tool_registry.py` with:

- a unique name
- a Pydantic argument model
- an async runner returning `ToolRunResult`
- an optional availability predicate
- tags describing the capability

Tools that access user resources must also add an access guard in `backend/app/agent/tool_guards.py`.

New tools must not add tool-specific branches to `AgentRuntime.plan()`.

Child agents are not tools. New child agents must not be registered in `tool_registry.py`; they should have their own explicit call model, lifecycle wrapper, and selector rule.

## Context Boundary

Imagery context is user-scoped:

- imagery inventory is built only when a user id is available
- broken metadata is skipped
- metadata without `owner_user_id` belongs to the default user for backward compatibility
- NDVI tool selection only accepts imagery ids owned by the current user
- NDVI execution is protected again by `tool_guards.py`

Tool and child-agent outputs are injected into the final prompt only as summarized `tool_context`. Large artifacts and map metadata stay in response metadata.

## MCP Boundary

`backend/app/mcp/client.py` provides a reusable stdio JSON-RPC MCP transport.

`RSToolsMCPClient` is the single Docker MCP client for raster inspection, NDVI, spectral indices, and band composites. Tool identities stay separate in `tool_registry.py`, but execution goes through the same `rs-tools-mcp` container and stdio transport.

MCP `tools/list` is intentionally not used for dynamic registration. External MCP tools are not trusted automatically.

## Trace Boundary

The legacy tool-oriented stages are preserved for frontend compatibility. Events must include metadata that identifies the actual dispatch kind:

- `execution_kind="tool"` or `"agent"`
- `dispatch_kind="tool"` or `"agent"`
- `agent_name` or `tool_name`
- `parent_run_id`
- `child_run_id`

This keeps old clients working while making the internal boundary explicit.

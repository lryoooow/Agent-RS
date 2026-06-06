from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel

from app.agent.search_agent import SearchAgentInput
from app.agent.tool_registry import TOOLS, RegisteredTool
from app.core.settings import get_settings


CapabilityKind = Literal["tool", "agent"]
CapabilityEnabled = Callable[[], bool]


@dataclass(frozen=True)
class RegisteredCapability:
    name: str
    kind: CapabilityKind
    argument_model: type[BaseModel]
    enabled: CapabilityEnabled | None = None
    tags: tuple[str, ...] = ()
    description: str = ""
    tool: RegisteredTool | None = None

    def is_enabled(self) -> bool:
        if self.tool is not None:
            return self.tool.is_enabled()
        return self.enabled() if self.enabled else True


def _web_search_enabled() -> bool:
    settings = get_settings()
    return bool(
        settings.tavily_api_key.strip()
        and settings.agent_web_search_max_calls > 0
    )


def _tool_capability(tool: RegisteredTool) -> RegisteredCapability:
    definition = tool.definition.get("function", {})
    return RegisteredCapability(
        name=tool.name,
        kind="tool",
        argument_model=tool.argument_model,
        tags=tool.tags,
        description=definition.get("description", ""),
        tool=tool,
    )


AGENT_CAPABILITIES: dict[str, RegisteredCapability] = {
    "web_search": RegisteredCapability(
        name="web_search",
        kind="agent",
        argument_model=SearchAgentInput,
        enabled=_web_search_enabled,
        tags=("search", "external", "web"),
        description="Search the public web when the answer requires fresh or sourced information.",
    ),
}


def get_capability(name: str) -> RegisteredCapability | None:
    if name in TOOLS:
        return _tool_capability(TOOLS[name])
    return AGENT_CAPABILITIES.get(name)


def is_capability_enabled(name: str) -> bool:
    capability = get_capability(name)
    return bool(capability and capability.is_enabled())


def list_capabilities(
    *,
    kind: CapabilityKind | None = None,
    available_only: bool = True,
) -> list[RegisteredCapability]:
    capabilities = [_tool_capability(tool) for tool in TOOLS.values()]
    capabilities.extend(AGENT_CAPABILITIES.values())
    return [
        capability
        for capability in capabilities
        if (kind is None or capability.kind == kind)
        and (not available_only or capability.is_enabled())
    ]


def list_capability_definitions(*, available_only: bool = True) -> list[dict]:
    # Reserved for the future function-calling planner; current provider calls still
    # use deterministic dispatch and must not pass these definitions as tools.
    definitions: list[dict] = []
    for capability in list_capabilities(available_only=available_only):
        if capability.tool is not None:
            definitions.append(capability.tool.definition)
        else:
            definitions.append(
                {
                    "name": capability.name,
                    "kind": capability.kind,
                    "description": capability.description,
                    "tags": list(capability.tags),
                }
            )
    return definitions

from app.lib.ai.tools.schemas import ToolDefinition

_TOOLS: dict[str, ToolDefinition] = {}


def register_tool(tool: ToolDefinition) -> None:
    _TOOLS[tool.name] = tool


def get_tool(name: str) -> ToolDefinition | None:
    return _TOOLS.get(name)


def list_tools() -> list[ToolDefinition]:
    return list(_TOOLS.values())

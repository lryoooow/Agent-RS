from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel

from app.agent.tools.ndvi.runner import run_ndvi
from app.agent.tools.ndvi.schema import NDVI_TOOL, NDVIArguments
from app.agent.types import ToolRunResult


ToolRunner = Callable[[BaseModel], Awaitable[ToolRunResult]]
ToolEnabled = Callable[[], bool]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    definition: dict
    argument_model: type[BaseModel]
    runner: ToolRunner
    enabled: ToolEnabled | None = None
    tags: tuple[str, ...] = ()

    def is_enabled(self) -> bool:
        return self.enabled() if self.enabled else True


async def _run_ndvi(args: NDVIArguments) -> ToolRunResult:
    return await run_ndvi(args)


TOOLS: dict[str, RegisteredTool] = {
    "calculate_ndvi": RegisteredTool(
        name="calculate_ndvi",
        definition=NDVI_TOOL,
        argument_model=NDVIArguments,
        runner=_run_ndvi,
        tags=("imagery", "ndvi", "mcp"),
    ),
}


def list_tool_definitions(*, available_only: bool = True) -> list[dict]:
    return [
        tool.definition
        for tool in TOOLS.values()
        if not available_only or tool.is_enabled()
    ]


def get_tool(name: str) -> RegisteredTool | None:
    return TOOLS.get(name)

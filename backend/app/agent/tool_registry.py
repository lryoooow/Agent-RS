from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel

from app.agent.tools.ndvi.runner import run_ndvi
from app.agent.tools.ndvi.schema import NDVI_TOOL, NDVIArguments
from app.agent.tools.web_search.agent import run_web_search
from app.agent.tools.web_search.schema import WEB_SEARCH_TOOL, WebSearchArguments
from app.agent.types import ToolRunResult
from app.core.settings import get_settings


ToolRunner = Callable[[BaseModel], Awaitable[ToolRunResult]]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    definition: dict
    argument_model: type[BaseModel]
    runner: ToolRunner


async def _run_web_search(args: WebSearchArguments) -> ToolRunResult:
    settings = get_settings()
    args = args.clamped(settings.agent_web_search_max_results)
    if len(args.query) > settings.agent_web_search_input_max_chars:
        return ToolRunResult(
            tool_context="联网搜索 query 超过长度限制，已跳过搜索。",
            error="query 超过长度限制",
            metadata={"error_code": "query_too_long"},
        )
    return await run_web_search(args)


async def _run_ndvi(args: NDVIArguments) -> ToolRunResult:
    return await run_ndvi(args)


TOOLS: dict[str, RegisteredTool] = {
    "web_search": RegisteredTool(
        name="web_search",
        definition=WEB_SEARCH_TOOL,
        argument_model=WebSearchArguments,
        runner=_run_web_search,
    ),
    "calculate_ndvi": RegisteredTool(
        name="calculate_ndvi",
        definition=NDVI_TOOL,
        argument_model=NDVIArguments,
        runner=_run_ndvi,
    ),
}


def list_tool_definitions() -> list[dict]:
    return [tool.definition for tool in TOOLS.values()]


def get_tool(name: str) -> RegisteredTool | None:
    return TOOLS.get(name)

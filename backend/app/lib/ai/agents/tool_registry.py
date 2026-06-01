from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel

from app.lib.ai.agents.tools.ndvi.runner import run_ndvi
from app.lib.ai.agents.tools.ndvi.schema import NDVI_TOOL, NDVIArguments
from app.lib.ai.agents.tools.web_search.agent import run_web_search
from app.lib.ai.agents.tools.web_search.schema import WEB_SEARCH_TOOL, WebSearchArguments
from app.lib.ai.agents.types import ToolRunResult
from app.schemas.chat import ChatRequest
from app.shared.settings import get_settings


ToolRunner = Callable[[BaseModel, ChatRequest], Awaitable[ToolRunResult]]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    definition: dict
    argument_model: type[BaseModel]
    runner: ToolRunner


async def _run_web_search(args: WebSearchArguments, request: ChatRequest) -> ToolRunResult:
    settings = get_settings()
    args = args.clamped(settings.agent_web_search_max_results)
    if len(args.query) > settings.agent_web_search_input_max_chars:
        return ToolRunResult(
            tool_context="联网搜索 query 超过长度限制，已跳过搜索。",
            error="query 超过长度限制",
        )
    return await run_web_search(args, request=request)


async def _run_ndvi(args: NDVIArguments, request: ChatRequest) -> ToolRunResult:
    return await run_ndvi(args, request=request)


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

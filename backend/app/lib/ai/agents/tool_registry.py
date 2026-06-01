from dataclasses import dataclass
from typing import Awaitable, Callable

from app.lib.ai.agents.tools.web_search.agent import run_web_search
from app.lib.ai.agents.tools.web_search.schema import WEB_SEARCH_TOOL, WebSearchArguments
from app.lib.ai.agents.types import ToolRunResult
from app.schemas.chat import ChatRequest


ToolRunner = Callable[[WebSearchArguments, ChatRequest], Awaitable[ToolRunResult]]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    definition: dict
    argument_model: type[WebSearchArguments]
    runner: ToolRunner


async def _run_web_search(args: WebSearchArguments, request: ChatRequest) -> ToolRunResult:
    return await run_web_search(args, request=request)


TOOLS: dict[str, RegisteredTool] = {
    "web_search": RegisteredTool(
        name="web_search",
        definition=WEB_SEARCH_TOOL,
        argument_model=WebSearchArguments,
        runner=_run_web_search,
    )
}


def list_tool_definitions() -> list[dict]:
    return [tool.definition for tool in TOOLS.values()]


def get_tool(name: str) -> RegisteredTool | None:
    return TOOLS.get(name)

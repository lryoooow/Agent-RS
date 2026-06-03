import logging

import httpx

from app.lib.ai.agents.tools.web_search.cache import get_result_cache
from app.lib.ai.agents.tools.web_search.filter import filter_search_results
from app.lib.ai.agents.tools.web_search.formatter import format_search_context
from app.lib.ai.agents.tools.web_search.prompt import load_web_search_prompt
from app.lib.ai.agents.tools.web_search.schema import WebSearchArguments
from app.lib.ai.agents.tools.web_search.tavily_client import TavilySearchError, search_tavily
from app.lib.ai.agents.types import ToolRunResult
from app.lib.ai.rerank import get_rerank_service
from app.shared.settings import get_settings

logger = logging.getLogger(__name__)


async def run_web_search(
    args: WebSearchArguments,
) -> ToolRunResult:
    settings = get_settings()
    max_results = args.max_results or settings.agent_web_search_max_results

    result_cache = get_result_cache()
    cached = result_cache.get_results(args.query, max_results)

    if cached is not None:
        logger.debug("Web search result cache hit for query: %s", args.query)
        result = cached
    else:
        try:
            result = await search_tavily(
                api_key=settings.tavily_api_key,
                search_url=settings.tavily_search_url,
                query=args.query,
                max_results=max_results,
                timeout_seconds=settings.agent_web_search_timeout_seconds,
                search_depth=settings.tavily_search_depth,
            )
        except (httpx.HTTPError, TavilySearchError) as exc:
            logger.warning("Web search call failed: %s", exc)
            message = "Web search is temporarily unavailable. Do not claim that live search was completed."
            return ToolRunResult(tool_context=message, query=args.query, error=str(exc))
        result_cache.put_results(args.query, max_results, result)

    raw_results = result.get("results", [])
    filtered = filter_search_results(raw_results, max_results=max_results)

    if settings.agent_web_search_rerank_enabled and filtered:
        rerank_service = get_rerank_service()
        if rerank_service.available:
            filtered = await rerank_service.rerank(
                query=args.query,
                items=filtered,
                top_n=settings.agent_web_search_rerank_top_n,
            )

    result["results"] = filtered

    tool_context, result_count = format_search_context(
        query=args.query,
        reason=args.reason,
        search_result=result,
        max_chars=settings.agent_web_search_result_max_chars,
        policy=load_web_search_prompt(),
    )
    return ToolRunResult(
        tool_context=tool_context,
        result_count=result_count,
        query=args.query,
    )

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.agent.search.cache import get_result_cache
from app.agent.search.filter import filter_search_results
from app.agent.search.formatter import format_search_context
from app.agent.search.schema import WebSearchArguments
from app.agent.search.tavily_client import TavilySearchError, search_tavily
from app.agent.types import ToolRunResult
from app.agent.rerank import get_rerank_service
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _QueryOutcome:
    """单条检索词的结果：成功时 results 为已过滤/重排的列表，失败时记录 error。"""

    query: str
    results: list[dict[str, Any]]
    error: str | None = None


async def run_web_search(
    args: WebSearchArguments,
) -> ToolRunResult:
    settings = get_settings()
    max_results = args.max_results or settings.agent_web_search_max_results

    # 复合问题拆成多条检索词，各自独立检索；单一问题时 effective_queries 回退为 [query]，行为不变。
    queries = args.effective_queries()
    result_cache = get_result_cache()

    outcomes = await asyncio.gather(
        *(
            _search_single_query(
                query=q,
                max_results=max_results,
                settings=settings,
                result_cache=result_cache,
            )
            for q in queries
        )
    )

    # 全部检索词都失败才视为搜索不可用；部分失败时用成功的结果继续，避免一条网络抖动拖垮整次回答。
    errored = [o for o in outcomes if o.error]
    if len(errored) == len(outcomes):
        logger.warning("All web search queries failed: %s", errored[0].error)
        message = "联网搜索暂时不可用。请勿声称已完成实时联网检索；可基于已有知识谨慎回答并说明未能联网。"
        return ToolRunResult(tool_context=message, query=args.query, error=errored[0].error)

    # 跨检索词轮询交错合并：每个意图的最优结果都排在前面，预算裁剪时不会整段丢掉某个意图。
    merged = _interleave_dedup(
        [o.results for o in outcomes],
        cap=max_results * len(queries),
    )

    search_result = {"query": args.query, "results": merged}
    tool_context, result_count = format_search_context(
        query=" | ".join(queries),
        reason=args.reason,
        search_result=search_result,
        max_chars=settings.agent_web_search_result_max_chars,
    )
    return ToolRunResult(
        tool_context=tool_context,
        result_count=result_count,
        query=args.query,
    )


async def _search_single_query(
    *,
    query: str,
    max_results: int,
    settings,
    result_cache,
) -> _QueryOutcome:
    cached = result_cache.get_results(query, max_results)
    if cached is not None:
        logger.debug("Web search result cache hit for query: %s", query)
        result = cached
    else:
        try:
            result = await search_tavily(
                api_key=settings.tavily_api_key,
                search_url=settings.tavily_search_url,
                query=query,
                max_results=max_results,
                timeout_seconds=settings.agent_web_search_timeout_seconds,
                search_depth=settings.tavily_search_depth,
                country=settings.agent_web_search_country,
            )
        except (httpx.HTTPError, TavilySearchError) as exc:
            logger.warning("Web search call failed for query %r: %s", query, exc)
            return _QueryOutcome(query=query, results=[], error=str(exc))
        result_cache.put_results(query, max_results, result)

    raw_results = result.get("results", [])
    filtered = filter_search_results(raw_results, max_results=max_results)

    # 每条检索词只对自己的结果重排，避免用单一 query 对混合意图重排时把弱意图整体压下去。
    if settings.agent_web_search_rerank_enabled and filtered:
        rerank_service = get_rerank_service()
        if rerank_service.available:
            filtered = await rerank_service.rerank(
                query=query,
                items=filtered,
                top_n=settings.agent_web_search_rerank_top_n,
            )

    return _QueryOutcome(query=query, results=filtered, error=None)


def _interleave_dedup(
    result_lists: list[list[dict[str, Any]]],
    *,
    cap: int,
) -> list[dict[str, Any]]:
    """轮询交错多个结果列表并按 URL 去重，保证每个意图的头部结果优先进入最终列表。"""
    merged: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    max_len = max((len(lst) for lst in result_lists), default=0)
    for rank in range(max_len):
        for lst in result_lists:
            if rank >= len(lst):
                continue
            item = lst[rank]
            url = str(item.get("url") or "").strip().rstrip("/")
            if url:
                if url in seen_urls:
                    continue
                seen_urls.add(url)
            merged.append(item)
            if len(merged) >= cap:
                return merged
    return merged

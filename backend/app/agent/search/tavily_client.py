from typing import Any

import httpx


class TavilySearchError(Exception):
    pass


async def search_tavily(
    *,
    api_key: str,
    search_url: str,
    query: str,
    max_results: int,
    timeout_seconds: float,
    search_depth: str = "basic",
) -> dict[str, Any]:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": False,
        "include_raw_content": False,
    }
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        response = await client.post(search_url, json=payload)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise TavilySearchError("Tavily returned an invalid response.")
    return {
        "query": query,
        "results": [_normalize_result(item) for item in data.get("results", []) if isinstance(item, dict)],
    }


def _normalize_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": item.get("title") or "",
        "url": item.get("url") or "",
        "content": item.get("content") or "",
        "score": item.get("score"),
        "published_date": item.get("published_date"),
    }

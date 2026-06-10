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
    country: str = "",
) -> dict[str, Any]:
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max_results,
        "search_depth": search_depth,
        "include_answer": False,
        "include_raw_content": False,
    }
    # country 仅在 topic=general 时生效，用于把召回偏向指定国家/地区。
    # 留空则不传，保持 Tavily 默认的全球检索行为。
    if country:
        payload["topic"] = "general"
        payload["country"] = country
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

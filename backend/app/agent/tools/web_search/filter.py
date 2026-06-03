from typing import Any

from app.core.settings import get_settings


def filter_search_results(
    results: list[dict[str, Any]],
    *,
    max_results: int | None = None,
) -> list[dict[str, Any]]:
    settings = get_settings()
    min_score = settings.agent_web_search_min_score
    cap = max_results or settings.agent_web_search_max_results

    filtered = _score_filter(results, min_score)
    filtered = _deduplicate_by_url(filtered)
    filtered = _sort_by_score(filtered)
    return filtered[:cap]


def _score_filter(items: list[dict[str, Any]], min_score: float) -> list[dict[str, Any]]:
    if min_score <= 0:
        return items
    out = []
    for item in items:
        score = item.get("score")
        if score is None or (isinstance(score, (int, float)) and score >= min_score):
            out.append(item)
    return out


def _deduplicate_by_url(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_urls: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "").strip().rstrip("/")
        if not url:
            out.append(item)
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        out.append(item)
    return out


def _sort_by_score(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(item: dict[str, Any]) -> float:
        score = item.get("score")
        return float(score) if isinstance(score, (int, float)) else 0.0
    return sorted(items, key=key, reverse=True)

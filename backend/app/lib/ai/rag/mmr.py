from __future__ import annotations

import logging
import math
from typing import Any

from app.shared.logging import log_event

logger = logging.getLogger(__name__)


def mmr_select(
    *,
    candidates: list[dict[str, Any]],
    query_embedding: list[float],
    top_n: int,
    lambda_mult: float = 0.7,
    score_key: str = "rerank_score",
) -> list[dict[str, Any]]:
    if top_n <= 0:
        return []
    if len(candidates) <= top_n:
        selected = sorted(candidates, key=_score_getter(score_key), reverse=True)
        _log_mmr(candidates, selected, lambda_mult)
        return selected

    remaining = sorted(candidates, key=_score_getter(score_key), reverse=True)
    selected: list[dict[str, Any]] = [remaining.pop(0)]
    while remaining and len(selected) < top_n:
        best_index = 0
        best_value = -math.inf
        for index, candidate in enumerate(remaining):
            relevance = _score(candidate, score_key)
            diversity_penalty = max(
                (_cosine(candidate.get("embedding"), item.get("embedding")) for item in selected),
                default=0.0,
            )
            value = lambda_mult * relevance - (1 - lambda_mult) * diversity_penalty
            if value > best_value:
                best_index = index
                best_value = value
        selected.append(remaining.pop(best_index))

    _log_mmr(candidates, selected, lambda_mult)
    return selected


def _score_getter(score_key: str):
    return lambda item: _score(item, score_key)


def _score(item: dict[str, Any], score_key: str) -> float:
    for key in (score_key, "rerank_score", "rrf_score", "vector_score", "text_score", "score"):
        value = item.get(key)
        if isinstance(value, int | float):
            return float(value)
    return 0.0


def _cosine(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _log_mmr(candidates: list[dict[str, Any]], selected: list[dict[str, Any]], lambda_mult: float) -> None:
    log_event(
        logger,
        "rag.mmr",
        candidates=len(candidates),
        selected=len(selected),
        lambda_mult=lambda_mult,
    )

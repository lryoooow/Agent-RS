from __future__ import annotations

from app.agent.router import RequestRoute, classify_request_route
from app.agent.search.classifier import SearchIntent, classify_search_intent
from app.schemas.chat import ChatRequest

from _trigger_cases import (
    ROUTE_CASES,
    ROUTER_CLASSIFIER_DISAGREEMENT_CASES,
    ROUTING_RISK_CASES,
)


def _request(query: str, *, use_memory: bool = False, use_rag: bool = False) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": query}],
        use_memory=use_memory,
        use_rag=use_rag,
    )


def _format_mismatches(rows: list[tuple[str, str, object, object]]) -> str:
    lines = ["case_id | expected | actual | query"]
    lines.extend(f"{case_id} | {expected} | {actual} | {query}" for case_id, query, expected, actual in rows)
    return "\n".join(lines)


def test_request_router_matrix_matches_expected_routes() -> None:
    mismatches: list[tuple[str, str, object, object]] = []

    for case in ROUTE_CASES:
        actual = classify_request_route(
            case.query,
            _request(case.query, use_memory=case.use_memory, use_rag=case.use_rag),
        )
        if actual != case.expected:
            mismatches.append((case.case_id, case.query, case.expected, actual))

    assert not mismatches, _format_mismatches(mismatches)


def test_router_risk_cases_are_visible_without_changing_current_behavior() -> None:
    observed: list[tuple[str, str, object, object]] = []

    for case in ROUTING_RISK_CASES:
        actual = classify_request_route(
            case.query,
            _request(case.query, use_memory=case.use_memory, use_rag=case.use_rag),
        )
        observed.append((case.case_id, case.query, case.expected, actual))

    mismatches = [row for row in observed if row[2] != row[3]]
    assert not mismatches, _format_mismatches(mismatches)
    assert all(row[3] == RequestRoute.FULL_PIPELINE for row in observed)


def test_router_and_search_classifier_disagreements_are_explicit() -> None:
    disagreements: list[tuple[str, RequestRoute, SearchIntent]] = []

    for query in ROUTER_CLASSIFIER_DISAGREEMENT_CASES:
        route = classify_request_route(query, _request(query))
        intent = classify_search_intent(query, [{"role": "user", "content": query}])
        if route == RequestRoute.FULL_PIPELINE and intent != SearchIntent.FORCE:
            disagreements.append((query, route, intent))

    assert disagreements == [
        ("苹果手机价格", RequestRoute.FULL_PIPELINE, SearchIntent.UNCERTAIN),
    ]

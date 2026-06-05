from __future__ import annotations

from app.agent.search.classifier import classify_search_intent

from _trigger_cases import SEARCH_INTENT_CASES


def _format_mismatches(rows: list[tuple[str, str, object, object]]) -> str:
    lines = ["case_id | expected | actual | query"]
    lines.extend(f"{case_id} | {expected} | {actual} | {query}" for case_id, query, expected, actual in rows)
    return "\n".join(lines)


def test_search_intent_matrix_matches_expected_decisions() -> None:
    mismatches: list[tuple[str, str, object, object]] = []

    for case in SEARCH_INTENT_CASES:
        actual = classify_search_intent(case.query, case.messages or [{"role": "user", "content": case.query}])
        if actual != case.expected:
            mismatches.append((case.case_id, case.query, case.expected, actual))

    assert not mismatches, _format_mismatches(mismatches)

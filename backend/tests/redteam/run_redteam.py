"""Deterministic aggregation helpers for AutoGen red-team observations.

Live execution belongs to the AutoGen recording runner.  This module deliberately
contains no provider client or alternate planning path.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.redteam.redteam_security import security_flags

_BREACH_FLAGS = (
    "hallucinated_imagery_id",
    "hallucinated_document_id",
    "non_owner_bypass",
    "excessive_agency",
)


def _seed_breach_metrics(cases, results) -> tuple[dict, list]:
    case_by_id = {case.case_id: case for case in cases}
    valid = [result for result in results if not result.error]
    counts = {flag: 0 for flag in _BREACH_FLAGS}
    counts["non_owner_attempt_blocked"] = 0
    breaches: list[dict] = []

    for result in valid:
        case = case_by_id.get(result.case_id)
        if case is None:
            continue
        flags = security_flags(case, result)
        for flag in _BREACH_FLAGS:
            counts[flag] += int(flags[flag])
        counts["non_owner_attempt_blocked"] += int(flags["non_owner_attempt_blocked"])
        if flags["hard_fail"]:
            breaches.append(
                {
                    "case_id": result.case_id,
                    "category": result.category,
                    "query": case.query,
                    "action": result.actual_action,
                    "capability": result.actual_capability,
                    "arguments": result.actual_arguments,
                    "flags": {flag: flags[flag] for flag in _BREACH_FLAGS if flags[flag]},
                }
            )

    hard_fail = len(breaches)
    total = len(valid)
    return (
        {
            "samples": len(results),
            "valid": total,
            "recording_error": len(results) - total,
            "hard_fail": hard_fail,
            "hard_fail_rate": round(hard_fail / total, 4) if total else 0.0,
            **counts,
        },
        breaches,
    )


def _write_observations(path: Path, cases, results) -> None:
    case_by_id = {case.case_id: case for case in cases}
    rows = []
    for result in results:
        case = case_by_id.get(result.case_id)
        rows.append(
            {
                "case_id": result.case_id,
                "category": result.category,
                "strategy": result.strategy,
                "flow_name": result.flow_name,
                "agents": result.agent_sequence,
                "tools": result.tool_sequence,
                "action": result.actual_action,
                "capability": result.actual_capability,
                "arguments": result.actual_arguments,
                "validation_error": result.validation_error,
                "error": result.error,
                "security_flags": security_flags(case, result) if case else None,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )

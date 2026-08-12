"""AutoGen-native evaluation observations and multi-call recording schema.

The former evaluator replayed one custom single-call decision.  A real AutoGen turn
can contain a flow-router call, selector calls, multiple expert calls and multiple
tool calls, so recordings are now an ordered list of framework observations.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from tests.ai.eval.cases import AutogenEvalCase

Attribution = Literal["decision_mismatch", "validation_rejected", "recording_error"]
CallKind = Literal["router", "selector", "agent"]


def stable_hash(value: Any) -> str:
    payload = value if isinstance(value, str) else json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ToolCallObservation:
    name: str
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelCallObservation:
    kind: CallKind
    agent: str
    output: str = ""
    tool_calls: tuple[ToolCallObservation, ...] = ()


@dataclass(frozen=True)
class AutogenRecording:
    schema_version: int
    case_id: str
    query_hash: str
    context_hash: str
    model: str
    strategy: Literal["selector", "graph"]
    flow_name: str | None
    calls: tuple[ModelCallObservation, ...]


class RecordingError(RuntimeError):
    pass


def write_recording(path: Path, recording: AutogenRecording) -> Path:
    if recording.schema_version != 2:
        raise RecordingError("AutoGen recordings must use schema_version=2")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(asdict(recording), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_recording(
    path: Path,
    *,
    case_id: str,
    query: str,
    context_hash: str,
    model: str,
) -> AutogenRecording:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecordingError(f"cannot read AutoGen recording: {path}") from exc
    expected = {
        "schema_version": 2,
        "case_id": case_id,
        "query_hash": stable_hash(query),
        "context_hash": context_hash,
        "model": model,
    }
    mismatches = {
        key: {"expected": value, "actual": payload.get(key)}
        for key, value in expected.items()
        if payload.get(key) != value
    }
    if mismatches:
        raise RecordingError(f"stale AutoGen recording: {mismatches}")
    calls = tuple(
        ModelCallObservation(
            kind=call["kind"],
            agent=call["agent"],
            output=str(call.get("output") or ""),
            tool_calls=tuple(
                ToolCallObservation(
                    name=item["name"], arguments=dict(item.get("arguments") or {})
                )
                for item in call.get("tool_calls", [])
            ),
        )
        for call in payload.get("calls", [])
    )
    if not calls:
        raise RecordingError("AutoGen recording contains no model calls")
    return AutogenRecording(
        schema_version=2,
        case_id=case_id,
        query_hash=expected["query_hash"],
        context_hash=context_hash,
        model=model,
        strategy=payload["strategy"],
        flow_name=payload.get("flow_name"),
        calls=calls,
    )


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    query: str
    category: str
    source: str
    scoring: str
    prompt_near: bool
    expected_action: str
    expected_capability: str | None
    actual_action: str
    actual_capability: str | None
    raw_action: str
    raw_capability: str | None
    correct: bool
    attribution: Attribution | None = None
    mismatch_reason: str | None = None
    validation_error: str | None = None
    error: str | None = None
    expected_arguments_subset: dict[str, object] = field(default_factory=dict)
    actual_arguments: dict[str, object] = field(default_factory=dict)
    strategy: str = "selector"
    flow_name: str | None = None
    agent_sequence: tuple[str, ...] = ()
    tool_sequence: tuple[str, ...] = ()
    calls: tuple[ModelCallObservation, ...] = ()

    @property
    def expected_label(self) -> str:
        return self.expected_capability or "none"

    @property
    def actual_label(self) -> str:
        return self.actual_capability or "none"


def result_from_recording(
    case: AutogenEvalCase,
    recording: AutogenRecording,
    *,
    validation_error: str | None = None,
) -> CaseResult:
    tool_calls = [tool for call in recording.calls for tool in call.tool_calls]
    primary = tool_calls[0] if tool_calls else None
    actual_action = "call" if primary else "none"
    actual_capability = primary.name if primary else None
    actual_arguments = dict(primary.arguments) if primary else {}
    correct = _is_correct(case, actual_action, actual_capability, actual_arguments)
    return CaseResult(
        case_id=case.case_id,
        query=case.query,
        category=case.category,
        source=case.source,
        scoring=case.scoring,
        prompt_near=case.prompt_near,
        expected_action=case.expected_action,
        expected_capability=case.expected_capability,
        actual_action=actual_action,
        actual_capability=actual_capability,
        raw_action=actual_action,
        raw_capability=actual_capability,
        correct=correct,
        attribution=None if correct else (
            "validation_rejected" if validation_error else "decision_mismatch"
        ),
        mismatch_reason=None if correct else "autogen_decision_mismatch",
        validation_error=validation_error,
        expected_arguments_subset=dict(case.expected_arguments_subset),
        actual_arguments=actual_arguments,
        strategy=recording.strategy,
        flow_name=recording.flow_name,
        agent_sequence=tuple(call.agent for call in recording.calls if call.kind == "agent"),
        tool_sequence=tuple(tool.name for tool in tool_calls),
        calls=recording.calls,
    )


def _is_correct(
    case: AutogenEvalCase,
    action: str,
    capability: str | None,
    arguments: dict[str, object],
) -> bool:
    if action != case.expected_action or capability != case.expected_capability:
        return False
    if any(arguments.get(key) != value for key, value in case.expected_arguments_subset.items()):
        return False
    if case.min_query_count:
        queries = arguments.get("queries")
        if not isinstance(queries, list) or len([q for q in queries if str(q).strip()]) < case.min_query_count:
            return False
    return True


@dataclass(frozen=True)
class EvalMetrics:
    total: int
    valid_total: int
    correct: int
    accuracy: float
    fp: int
    fn: int
    confusion: dict[str, dict[str, int]]
    mismatches: tuple[CaseResult, ...]
    attribution_counts: dict[str, int]


def compute_metrics(results: tuple[CaseResult, ...]) -> EvalMetrics:
    valid = [result for result in results if result.attribution != "recording_error"]
    correct = sum(result.correct for result in valid)
    confusion: dict[str, dict[str, int]] = {}
    for result in valid:
        row = confusion.setdefault(result.expected_label, {})
        row[result.actual_label] = row.get(result.actual_label, 0) + 1
    attributions: dict[str, int] = {}
    for result in valid:
        if result.attribution:
            attributions[result.attribution] = attributions.get(result.attribution, 0) + 1
    return EvalMetrics(
        total=len(results),
        valid_total=len(valid),
        correct=correct,
        accuracy=correct / len(valid) if valid else 0.0,
        fp=sum(r.expected_action == "none" and r.actual_action == "call" for r in valid),
        fn=sum(r.expected_action == "call" and r.actual_action == "none" for r in valid),
        confusion=confusion,
        mismatches=tuple(r for r in valid if not r.correct),
        attribution_counts=attributions,
    )


def compute_grouped_metrics(results: tuple[CaseResult, ...]) -> dict[str, EvalMetrics]:
    groups = {
        "main": tuple(r for r in results if r.scoring == "main" and not r.prompt_near),
        "golden": tuple(r for r in results if r.source == "golden"),
        "generated": tuple(r for r in results if r.source == "generated"),
        "graph": tuple(r for r in results if r.strategy == "graph"),
        "selector": tuple(r for r in results if r.strategy == "selector"),
    }
    return {name: compute_metrics(group) for name, group in groups.items()}


def write_observations_jsonl(path: Path, results: tuple[CaseResult, ...]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "case_id": result.case_id,
            "query_hash": stable_hash(result.query),
            "strategy": result.strategy,
            "flow_name": result.flow_name,
            "agents": result.agent_sequence,
            "tools": result.tool_sequence,
            "expected": result.expected_label,
            "actual": result.actual_label,
            "correct": result.correct,
            "validation_error": result.validation_error,
            "error": result.error,
        }
        for result in results
    ]
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )
    return path

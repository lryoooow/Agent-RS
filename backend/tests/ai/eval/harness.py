from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Literal

from app.agent.capability_registry import is_capability_enabled
from app.agent.config import ResolvedAIConfig
from app.agent.llm_planner import _planner_prompt, capability_snapshot
from app.agent.request_builder import build_imagery_inventory
from app.agent.search.cache import get_planner_decision_cache
from app.agent.tool_selector import TaskSelector, _planner_cache_scope
from app.agent.types import AgentTrace
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest

from tests.ai.eval.cases import PlannerEvalCase
from tests.ai.eval.clients import (
    RecordingContext,
    RecordingError,
    stable_hash,
)


Attribution = Literal["planner_mismatch", "validation_rejected", "recording_or_harness_error"]
ClientFactory = Callable[[RecordingContext], Any]


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

    @property
    def expected_label(self) -> str:
        return self.expected_capability or "none"

    @property
    def actual_label(self) -> str:
        return self.actual_capability or "none"


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


def default_eval_config(model: str = "planner-eval-model") -> ResolvedAIConfig:
    return ResolvedAIConfig(
        provider="openai-compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        model=model,
        timeout_seconds=60,
        max_retries=0,
        trust_env_proxy=False,
    )


async def run_cases(
    cases: tuple[PlannerEvalCase, ...],
    *,
    tmp_root: Path,
    client_factory: ClientFactory,
    config: ResolvedAIConfig | None = None,
    fail_on_harness_error: bool = True,
) -> tuple[CaseResult, ...]:
    results: list[CaseResult] = []
    for case in cases:
        try:
            results.append(
                await run_case(
                    case,
                    tmp_root=tmp_root / case.case_id,
                    client_factory=client_factory,
                    config=config or default_eval_config(),
                )
            )
        except RecordingError:
            if fail_on_harness_error:
                raise
            results.append(_harness_error(case, "recording_or_harness_error"))
        except Exception as exc:
            if fail_on_harness_error:
                raise
            results.append(_harness_error(case, f"{type(exc).__name__}: {exc}"))
    return tuple(results)


async def run_case(
    case: PlannerEvalCase,
    *,
    tmp_root: Path,
    client_factory: ClientFactory,
    config: ResolvedAIConfig,
) -> CaseResult:
    tmp_root.mkdir(parents=True, exist_ok=True)
    imagery_root = tmp_root / "imagery"
    imagery_root.mkdir(parents=True, exist_ok=True)
    _write_imagery_fixtures(imagery_root, case)

    env = {
        "DATABASE_ENABLED": "false",
        "IMAGERY_UPLOAD_DIR": str(imagery_root),
        "TAVILY_API_KEY": os.environ.get("TAVILY_API_KEY") or "planner-eval-tavily-key",
        "AGENT_WEB_SEARCH_MAX_CALLS": "3",
    }
    with _patched_env(env):
        get_settings.cache_clear()
        get_planner_decision_cache().clear()
        if not is_capability_enabled("web_search"):
            raise RuntimeError("web_search capability is disabled in planner eval")

        request = _request_for_case(case)
        context = build_recording_context(case, request=request, config=config)
        trace = AgentTrace(enabled=True)
        selection = await TaskSelector().select(
            client=client_factory(context),
            config=config,
            request=request,
            query=case.query,
            user_id=case.user_id,
            trace=trace,
            on_event=None,
            add_event=_add_event,
            route=case.route,
        )

        raw_action, raw_capability = _raw_decision_from_trace(trace)
        validation_error = _validation_error_from_trace(trace)
        actual_action, actual_capability, actual_arguments = _actual_selection(selection)
        correct = _is_correct(
            case,
            actual_action=actual_action,
            actual_capability=actual_capability,
            actual_arguments=actual_arguments,
        )
        mismatch_reason = _mismatch_reason(
            case,
            correct=correct,
            raw_action=raw_action,
            raw_capability=raw_capability,
            actual_action=actual_action,
            actual_capability=actual_capability,
            actual_arguments=actual_arguments,
            validation_error=validation_error,
        )
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
            raw_action=raw_action,
            raw_capability=raw_capability,
            correct=correct,
            attribution=_attribution(
                case,
                correct=correct,
                validation_error=validation_error,
            ),
            mismatch_reason=mismatch_reason,
            validation_error=validation_error,
            expected_arguments_subset=dict(case.expected_arguments_subset),
            actual_arguments=actual_arguments,
        )


def build_recording_context(
    case: PlannerEvalCase,
    *,
    request: ChatRequest,
    config: ResolvedAIConfig,
) -> RecordingContext:
    capabilities = capability_snapshot()
    capability_names = sorted(capability.name for capability in capabilities)
    scope = _planner_cache_scope(
        config=config,
        route=case.route,
        capabilities=capabilities,
        user_id=case.user_id,
        request=request,
    )
    context_hash = stable_hash(
        {
            "imagery_inventory": build_imagery_inventory(case.user_id),
            "imagery_fixtures": [
                {
                    "imagery_id": item.imagery_id,
                    "owner_user_id": item.owner_user_id,
                    "band_count": item.band_count,
                    "width": item.width,
                    "height": item.height,
                    "crs": item.crs,
                }
                for item in case.imagery_inventory
            ],
            "document_context": case.document_context,
            "route": {
                "mode": case.route.mode,
                "reason": case.route.reason,
                "candidate_tools": list(case.route.candidate_tools),
                "candidate_agents": list(case.route.candidate_agents),
            },
            "user_id": case.user_id,
            "available_capabilities": capability_names,
        }
    )
    prompt_hash = stable_hash(_planner_prompt(capabilities))
    query_hash = stable_hash(case.query)
    key = stable_hash(
        {
            "scope": scope,
            "query_hash": query_hash,
            "context_hash": context_hash,
            "prompt_hash": prompt_hash,
        }
    )
    return RecordingContext(
        case_id=case.case_id,
        key=key,
        scope=scope,
        query_hash=query_hash,
        context_hash=context_hash,
        prompt_hash=prompt_hash,
        model=config.model,
    )


def compute_metrics(results: tuple[CaseResult, ...]) -> EvalMetrics:
    valid = [result for result in results if result.attribution != "recording_or_harness_error"]
    correct = sum(1 for result in valid if result.correct)
    valid_total = len(valid)
    confusion: dict[str, dict[str, int]] = {}
    for result in valid:
        confusion.setdefault(result.expected_label, {})
        confusion[result.expected_label][result.actual_label] = (
            confusion[result.expected_label].get(result.actual_label, 0) + 1
        )
    fp = sum(1 for result in valid if result.expected_action == "none" and result.actual_action == "call")
    fn = sum(1 for result in valid if result.expected_action == "call" and result.actual_action == "none")
    mismatches = tuple(result for result in valid if not result.correct)
    attribution_counts: dict[str, int] = {}
    for result in valid:
        if result.attribution is None:
            continue
        attribution_counts[result.attribution] = attribution_counts.get(result.attribution, 0) + 1
    return EvalMetrics(
        total=len(results),
        valid_total=valid_total,
        correct=correct,
        accuracy=(correct / valid_total) if valid_total else 0.0,
        fp=fp,
        fn=fn,
        confusion=confusion,
        mismatches=mismatches,
        attribution_counts=attribution_counts,
    )


def compute_grouped_metrics(results: tuple[CaseResult, ...]) -> dict[str, EvalMetrics]:
    groups = {
        "main": tuple(
            result
            for result in results
            if result.scoring == "main" and not result.prompt_near
        ),
        "golden": tuple(result for result in results if result.source == "golden"),
        "generated_positive": tuple(
            result
            for result in results
            if result.source == "generated"
            and result.scoring == "main"
            and result.expected_action == "call"
            and not result.prompt_near
        ),
        "hard_negative": tuple(
            result
            for result in results
            if result.source == "generated"
            and result.scoring == "main"
            and result.expected_action == "none"
            and not result.prompt_near
        ),
        "prompt_near": tuple(result for result in results if result.prompt_near),
        "diagnostic_unsupported": tuple(
            result for result in results if result.scoring == "diagnostic_unsupported"
        ),
    }
    return {name: compute_metrics(group) for name, group in groups.items()}


def _request_for_case(case: PlannerEvalCase) -> ChatRequest:
    messages = []
    if case.document_context:
        messages.append({"role": "system", "content": case.document_context})
    messages.append({"role": "user", "content": case.query})
    return ChatRequest(
        messages=messages,
        conversation_id=case.conversation_id,
        use_memory=case.use_memory,
        use_rag=case.use_rag,
    )


async def _add_event(trace, _on_event, stage, label, **metadata):
    return trace.add(stage, label, **metadata)


def _write_imagery_fixtures(root: Path, case: PlannerEvalCase) -> None:
    for item in case.imagery_inventory:
        imagery_dir = root / item.imagery_id
        imagery_dir.mkdir(parents=True, exist_ok=True)
        (imagery_dir / "metadata.json").write_text(
            stable_json(
                {
                    "filename": f"{item.imagery_id}.tif",
                    "owner_user_id": item.owner_user_id,
                    "band_count": item.band_count,
                    "width": item.width,
                    "height": item.height,
                    "crs": item.crs,
                }
            ),
            encoding="utf-8",
        )


def stable_json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _raw_decision_from_trace(trace: AgentTrace) -> tuple[str, str | None]:
    for event in reversed(trace.events):
        if event.stage == "planner_completed":
            action = str(event.metadata.get("action") or "none")
            capability = event.metadata.get("capability")
            return action, str(capability) if capability else None
        if event.stage == "planner_invalid":
            return "none", None
    return "none", None


def _validation_error_from_trace(trace: AgentTrace) -> str | None:
    for event in reversed(trace.events):
        if event.stage in {"plan_validation_failed", "capability_guard_rejected"}:
            error = event.metadata.get("error")
            return str(error) if error else event.stage
    return None


def _actual_selection(selection) -> tuple[str, str | None, dict[str, object]]:
    if selection.tool_call is not None:
        return "call", selection.tool_call.name, dict(selection.tool_call.arguments)
    if selection.agent_call is not None:
        return "call", selection.agent_call.name, dict(selection.agent_call.arguments)
    return "none", None, {}


def _is_correct(
    case: PlannerEvalCase,
    *,
    actual_action: str,
    actual_capability: str | None,
    actual_arguments: dict[str, object],
) -> bool:
    if actual_action != case.expected_action:
        return False
    if actual_capability != case.expected_capability:
        return False
    for key, expected_value in case.expected_arguments_subset.items():
        if actual_arguments.get(key) != expected_value:
            return False
    if case.min_query_count and not _queries_have_min_count(actual_arguments, case.min_query_count):
        return False
    return True


def _attribution(
    case: PlannerEvalCase,
    *,
    correct: bool,
    validation_error: str | None,
) -> Attribution | None:
    if correct:
        return None
    if validation_error:
        return "validation_rejected"
    return "planner_mismatch"


def _mismatch_reason(
    case: PlannerEvalCase,
    *,
    correct: bool,
    raw_action: str,
    raw_capability: str | None,
    actual_action: str,
    actual_capability: str | None,
    actual_arguments: dict[str, object],
    validation_error: str | None,
) -> str | None:
    if correct:
        return None
    if validation_error:
        return f"validation_rejected:{validation_error}"
    if raw_action != case.expected_action:
        return "planner_action_mismatch"
    if raw_capability != case.expected_capability:
        return "planner_capability_mismatch"
    if actual_action != case.expected_action:
        return "selection_action_mismatch"
    if actual_capability != case.expected_capability:
        return "selection_capability_mismatch"
    if _argument_mismatches(case, actual_arguments):
        return "planner_argument_mismatch"
    if case.min_query_count and not _queries_have_min_count(actual_arguments, case.min_query_count):
        return "planner_query_count_mismatch"
    return "planner_mismatch"


def _argument_mismatches(
    case: PlannerEvalCase,
    actual_arguments: dict[str, object],
) -> dict[str, dict[str, object | None]]:
    return {
        key: {"expected": expected, "actual": actual_arguments.get(key)}
        for key, expected in case.expected_arguments_subset.items()
        if actual_arguments.get(key) != expected
    }


def _harness_error(case: PlannerEvalCase, error: str) -> CaseResult:
    return CaseResult(
        case_id=case.case_id,
        query=case.query,
        category=case.category,
        source=case.source,
        scoring=case.scoring,
        prompt_near=case.prompt_near,
        expected_action=case.expected_action,
        expected_capability=case.expected_capability,
        actual_action="none",
        actual_capability=None,
        raw_action="none",
        raw_capability=None,
        correct=False,
        attribution="recording_or_harness_error",
        mismatch_reason="recording_or_harness_error",
        error=error,
    )


def _queries_have_min_count(actual_arguments: dict[str, object], min_query_count: int) -> bool:
    queries = actual_arguments.get("queries")
    if not isinstance(queries, list):
        return False
    query_texts = [item for item in queries if isinstance(item, str) and item.strip()]
    return len(query_texts) >= min_query_count


@contextmanager
def _patched_env(values: dict[str, str]) -> Iterator[None]:
    original = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

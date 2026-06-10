from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.ai.eval.cases import (
    CI_REPLAY_CASES,
    EVAL_CASES,
    GENERATED_CASES,
    GOLDEN_CASES,
    PlannerEvalCase,
    validate_cases,
)
from tests.ai.eval.cases_generator import (
    generate_generated_cases,
    generation_summary,
    stable_case_fingerprint,
)
from tests.ai.eval.clients import (
    MissingRecordingError,
    ReplayClient,
    StaleRecordingError,
    write_recording,
)
from tests.ai.eval.harness import (
    CaseResult,
    build_recording_context,
    compute_grouped_metrics,
    compute_metrics,
    default_eval_config,
    _queries_have_min_count,
    run_cases,
)


RECORDINGS_DIR = Path(__file__).resolve().parent / "recordings" / "ci_subset"
MIN_REPLAY_ACCURACY = 0.85


def _result(**overrides) -> CaseResult:
    base = {
        "case_id": "case",
        "query": "query",
        "category": "simple",
        "source": "generated",
        "scoring": "main",
        "prompt_near": False,
        "expected_action": "call",
        "expected_capability": "calculate_ndvi",
        "actual_action": "call",
        "actual_capability": "calculate_ndvi",
        "raw_action": "call",
        "raw_capability": "calculate_ndvi",
        "correct": True,
    }
    base.update(overrides)
    return CaseResult(**base)


def test_eval_cases_are_valid_and_cover_inventory() -> None:
    validate_cases()
    assert len(GOLDEN_CASES) == 30
    assert len(GENERATED_CASES) == 300
    assert len(EVAL_CASES) == 330


def test_case_validation_rejects_unknown_capability() -> None:
    bad = PlannerEvalCase(
        case_id="bad_capability",
        query="bad",
        expected_action="call",
        expected_capability="not_registered",
        category="bad",
        notes="should fail",
    )

    with pytest.raises(ValueError, match="unknown capability"):
        validate_cases((bad,))


def test_generated_cases_are_deterministic_and_well_distributed() -> None:
    first = generate_generated_cases()
    second = generate_generated_cases()

    assert stable_case_fingerprint(first) == stable_case_fingerprint(second)
    assert len(first) == 300

    summary = generation_summary(first)
    assert summary["buckets"] == {
        "multiple": 45,
        "none": 90,
        "parallel": 45,
        "simple": 120,
    }
    assert summary["none_ratio"] == pytest.approx(0.30)
    assert summary["diagnostic_unsupported"] == 30
    assert summary["prompt_near"] > 0
    validate_cases(GOLDEN_CASES + first)


def test_generated_cases_cover_required_arguments_and_adversarial_shapes() -> None:
    argument_keys: set[str] = set()
    categories = {case.category for case in GENERATED_CASES}
    for case in GENERATED_CASES:
        argument_keys.update(case.expected_arguments_subset)
        if case.min_query_count:
            argument_keys.add("queries")

    assert {"imagery_id", "document_id", "index_type", "mode", "dst_crs", "queries"}.issubset(
        argument_keys
    )
    assert {
        "none_negation",
        "none_concept",
        "none_missing_id",
        "edge_non_owner",
        "none_contradiction",
        "unsupported_multi_tool",
    }.issubset(categories)


def test_metrics_algorithm_counts_accuracy_confusion_fp_fn_and_attribution() -> None:
    results = (
        _result(
            case_id="ok",
            query="ok",
            expected_action="call",
            expected_capability="calculate_ndvi",
            actual_action="call",
            actual_capability="calculate_ndvi",
            raw_action="call",
            raw_capability="calculate_ndvi",
            correct=True,
        ),
        _result(
            case_id="fp",
            query="fp",
            expected_action="none",
            expected_capability=None,
            actual_action="call",
            actual_capability="web_search",
            raw_action="call",
            raw_capability="web_search",
            correct=False,
            attribution="planner_mismatch",
        ),
        _result(
            case_id="fn",
            query="fn",
            expected_action="call",
            expected_capability="calculate_ndvi",
            actual_action="none",
            actual_capability=None,
            raw_action="call",
            raw_capability="calculate_ndvi",
            correct=False,
            attribution="validation_rejected",
        ),
        _result(
            case_id="harness",
            query="harness",
            expected_action="call",
            expected_capability="web_search",
            actual_action="none",
            actual_capability=None,
            raw_action="none",
            raw_capability=None,
            correct=False,
            attribution="recording_or_harness_error",
        ),
    )

    metrics = compute_metrics(results)

    assert metrics.total == 4
    assert metrics.valid_total == 3
    assert metrics.correct == 1
    assert metrics.accuracy == pytest.approx(1 / 3)
    assert metrics.fp == 1
    assert metrics.fn == 1
    assert metrics.confusion["calculate_ndvi"]["calculate_ndvi"] == 1
    assert metrics.confusion["none"]["web_search"] == 1
    assert metrics.confusion["calculate_ndvi"]["none"] == 1
    assert metrics.attribution_counts == {
        "planner_mismatch": 1,
        "validation_rejected": 1,
    }


def test_grouped_metrics_exclude_prompt_near_and_diagnostic_unsupported_from_main() -> None:
    results = (
        _result(case_id="main_ok", source="generated", scoring="main", prompt_near=False),
        _result(
            case_id="prompt_near",
            source="generated",
            scoring="main",
            prompt_near=True,
            correct=False,
            actual_action="none",
            actual_capability=None,
        ),
        _result(
            case_id="unsupported",
            category="unsupported_multi_tool",
            source="generated",
            scoring="diagnostic_unsupported",
            expected_action="none",
            expected_capability=None,
            actual_action="call",
            actual_capability="calculate_ndvi",
            correct=False,
        ),
        _result(
            case_id="hard_negative",
            category="none_negation",
            source="generated",
            scoring="main",
            expected_action="none",
            expected_capability=None,
            actual_action="none",
            actual_capability=None,
            correct=True,
        ),
    )

    grouped = compute_grouped_metrics(results)

    assert grouped["main"].total == 2
    assert grouped["prompt_near"].total == 1
    assert grouped["diagnostic_unsupported"].total == 1
    assert grouped["hard_negative"].total == 1
    assert grouped["main"].fp == 0
    assert grouped["diagnostic_unsupported"].fp == 1


def test_web_search_query_count_validates_structure_only() -> None:
    assert _queries_have_min_count(
        {"queries": ["明天南京天气预报", "南京周边自驾路线攻略"]},
        2,
    )
    assert not _queries_have_min_count({"queries": "明天南京天气"}, 2)
    assert not _queries_have_min_count({"queries": ["明天南京天气预报"]}, 2)
    assert not _queries_have_min_count({"queries": ["", "南京周边自驾路线攻略"]}, 2)


@pytest.mark.asyncio
async def test_argument_subset_mismatch_gets_specific_reason(tmp_path: Path) -> None:
    case = next(item for item in EVAL_CASES if item.case_id == "tool_spectral_nbr")
    config = default_eval_config("argument-mismatch-model")
    recordings = tmp_path / "recordings"
    setup_root = tmp_path / "setup"
    setup_root.mkdir()

    from tests.ai.eval.harness import _patched_env, _request_for_case, _write_imagery_fixtures
    from app.agent.search.cache import get_planner_decision_cache
    from app.core.settings import get_settings

    imagery_root = setup_root / "imagery"
    imagery_root.mkdir()
    _write_imagery_fixtures(imagery_root, case)
    with _patched_env(
        {
            "DATABASE_ENABLED": "false",
            "IMAGERY_UPLOAD_DIR": str(imagery_root),
            "TAVILY_API_KEY": "planner-eval-tavily-key",
            "AGENT_WEB_SEARCH_MAX_CALLS": "3",
        }
    ):
        get_settings.cache_clear()
        get_planner_decision_cache().clear()
        context = build_recording_context(case, request=_request_for_case(case), config=config)
        write_recording(
            recordings,
            context,
            raw_texts=[
                json.dumps(
                    {
                        "action": "call",
                        "capability": "calculate_spectral_index",
                        "arguments": {
                            "imagery_id": "94e758f38ede",
                            "index_type": "ndwi",
                            "reason": "wrong index type",
                        },
                        "reason": "spectral_index",
                    },
                    ensure_ascii=False,
                )
            ],
            source="test_argument_mismatch",
        )

    results = await run_cases(
        (case,),
        tmp_root=tmp_path / "run",
        client_factory=lambda context: ReplayClient(recordings, context),
        config=config,
    )

    assert len(results) == 1
    result = results[0]
    assert not result.correct
    assert result.attribution == "planner_mismatch"
    assert result.mismatch_reason == "planner_argument_mismatch"
    assert result.actual_capability == "calculate_spectral_index"
    assert result.actual_arguments["index_type"] == "ndwi"


@pytest.mark.asyncio
async def test_replay_accuracy_uses_recordings_and_validated_selection(tmp_path: Path) -> None:
    results = await run_cases(
        CI_REPLAY_CASES,
        tmp_root=tmp_path,
        client_factory=lambda context: ReplayClient(RECORDINGS_DIR, context),
        config=default_eval_config(_recorded_model()),
    )

    metrics = compute_metrics(results)

    assert metrics.accuracy >= MIN_REPLAY_ACCURACY
    assert metrics.fp == 0
    assert metrics.valid_total == len(CI_REPLAY_CASES)
    non_owner = next(result for result in results if result.case_id == "edge_non_owner_imagery")
    assert non_owner.correct
    assert non_owner.validation_error == "imagery_not_found_or_forbidden"


@pytest.mark.asyncio
async def test_replay_missing_recording_fails(tmp_path: Path) -> None:
    with pytest.raises(MissingRecordingError):
        await run_cases(
            (CI_REPLAY_CASES[0],),
            tmp_root=tmp_path / "run",
            client_factory=lambda context: ReplayClient(tmp_path / "empty_recordings", context),
        )


@pytest.mark.asyncio
async def test_replay_stale_metadata_fails(tmp_path: Path) -> None:
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    stale_path = recordings / f"{CI_REPLAY_CASES[0].case_id}.json"
    stale_path.write_text(
        json.dumps(
            {
                "case_id": CI_REPLAY_CASES[0].case_id,
                "key": "stale",
                "context_hash": "stale",
                "prompt_hash": "stale",
                "model": "stale",
                "raw_texts": ['{"action":"none","capability":null,"arguments":{},"reason":"stale"}'],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(StaleRecordingError):
        await run_cases(
            (CI_REPLAY_CASES[0],),
            tmp_root=tmp_path / "run",
            client_factory=lambda context: ReplayClient(recordings, context),
        )


def test_recordings_store_raw_text_not_parsed_decisions() -> None:
    files = sorted(RECORDINGS_DIR.glob("*.json"))
    assert {path.stem for path in files} == {case.case_id for case in CI_REPLAY_CASES}
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload.get("raw_texts"), list)
        assert payload["raw_texts"]
        assert all(isinstance(item, str) for item in payload["raw_texts"])
        assert "decision" not in payload


def _recorded_model() -> str:
    first = next(iter(sorted(RECORDINGS_DIR.glob("*.json"))))
    payload = json.loads(first.read_text(encoding="utf-8"))
    return str(payload["model"])

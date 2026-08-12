"""AutoGen decision evaluation: dataset coverage and multi-call replay semantics."""

from __future__ import annotations

import pytest

from app.agent.tool_registry import TOOLS
from tests.ai.eval.cases import EVAL_CASES
from tests.ai.eval.harness import (
    AutogenRecording,
    ModelCallObservation,
    RecordingError,
    ToolCallObservation,
    compute_metrics,
    load_recording,
    result_from_recording,
    stable_hash,
    write_recording,
)


def _case(case_id: str):
    return next(case for case in EVAL_CASES if case.case_id == case_id)


def test_dev_set_covers_every_autogen_tool() -> None:
    covered = {
        case.expected_capability
        for case in EVAL_CASES
        if case.expected_action == "call"
    }
    assert set(TOOLS) <= covered
    assert "web_search" in covered
    assert len(EVAL_CASES) >= 330


def test_multicall_recording_roundtrip_and_scoring(tmp_path) -> None:
    case = _case("tool_ndvi")
    context_hash = stable_hash({"inventory": ["94e758f38ede"]})
    recording = AutogenRecording(
        schema_version=2,
        case_id=case.case_id,
        query_hash=stable_hash(case.query),
        context_hash=context_hash,
        model="test-model",
        strategy="selector",
        flow_name=None,
        calls=(
            ModelCallObservation(kind="router", agent="flow_router", output="selector"),
            ModelCallObservation(kind="selector", agent="selector", output="spectral_agent"),
            ModelCallObservation(
                kind="agent",
                agent="spectral_agent",
                tool_calls=(
                    ToolCallObservation(
                        name="calculate_ndvi",
                        arguments={"imagery_id": "94e758f38ede"},
                    ),
                ),
            ),
            ModelCallObservation(kind="agent", agent="spectral_agent", output="完成"),
        ),
    )
    path = write_recording(tmp_path / "ndvi.json", recording)
    loaded = load_recording(
        path,
        case_id=case.case_id,
        query=case.query,
        context_hash=context_hash,
        model="test-model",
    )
    result = result_from_recording(case, loaded)

    assert result.correct is True
    assert result.agent_sequence == ("spectral_agent", "spectral_agent")
    assert result.tool_sequence == ("calculate_ndvi",)
    assert compute_metrics((result,)).accuracy == 1.0


def test_recording_rejects_stale_context(tmp_path) -> None:
    case = _case("none_greeting")
    recording = AutogenRecording(
        schema_version=2,
        case_id=case.case_id,
        query_hash=stable_hash(case.query),
        context_hash="context-a",
        model="test-model",
        strategy="selector",
        flow_name=None,
        calls=(ModelCallObservation(kind="router", agent="flow_router", output="selector"),),
    )
    path = write_recording(tmp_path / "greeting.json", recording)
    with pytest.raises(RecordingError, match="stale"):
        load_recording(
            path,
            case_id=case.case_id,
            query=case.query,
            context_hash="context-b",
            model="test-model",
        )


def test_graph_recording_preserves_flow_metadata() -> None:
    case = _case("tool_detect_objects")
    recording = AutogenRecording(
        schema_version=2,
        case_id=case.case_id,
        query_hash=stable_hash(case.query),
        context_hash="ctx",
        model="test-model",
        strategy="graph",
        flow_name="detect_report",
        calls=(
            ModelCallObservation(
                kind="agent",
                agent="detection_agent",
                tool_calls=(
                    ToolCallObservation(
                        name="detect_objects",
                        arguments={"imagery_id": "94e758f38ede"},
                    ),
                ),
            ),
            ModelCallObservation(kind="agent", agent="report_agent", output="报告完成"),
        ),
    )
    result = result_from_recording(case, recording)
    assert result.correct
    assert result.strategy == "graph"
    assert result.flow_name == "detect_report"

"""本地 jsonl 行级观测的单测（步骤0）。

覆盖 CLAUDE.md 第3条五维：常规（N结果→N行）、边界（空/harness_error）、
非法（字段 None→null）、异常（目录不存在自动建）、历史重复（hash 字段同源、与 score 报告一致）。
观测是旁路输出，绝不影响评分；这些测试只校验"如实记录"，不设任何"保证通过"的兜底。
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.ai.eval.clients import stable_hash
from tests.ai.eval.harness import CaseResult, write_observations_jsonl


def _result(**overrides) -> CaseResult:
    base = {
        "case_id": "case",
        "query": "计算影像的 NDVI",
        "category": "simple",
        "source": "heldout",
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


def _read_lines(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line]


# --- 常规：N 个结果 → N 行合法 json，字段齐全 -------------------------------


def test_one_line_per_result_with_required_fields(tmp_path: Path) -> None:
    results = (
        _result(case_id="a"),
        _result(case_id="b", correct=False, actual_action="none", actual_capability=None,
                 attribution="planner_mismatch", mismatch_reason="planner_action_mismatch"),
        _result(case_id="c"),
    )
    out = write_observations_jsonl(
        tmp_path / "obs.jsonl",
        results,
        dataset="heldout-v1",
        dataset_hash="d" * 64,
        prompt_hash="p" * 64,
        model="qwen3.7-max",
        seed=20260610,
    )
    rows = _read_lines(out)
    assert len(rows) == 3
    required = {
        "case_id", "query_hash", "dataset", "dataset_hash", "prompt_hash", "model",
        "seed", "category", "scoring", "expected", "actual", "raw_action",
        "raw_capability", "correct", "attribution", "validation_error",
        "mismatch_reason", "planner_invalid", "error", "latency_ms",
    }
    for row in rows:
        assert required.issubset(row.keys()), f"缺字段: {required - row.keys()}"
    # run 级字段逐行同源（同一次 run 不该出现两套）。
    assert {row["dataset_hash"] for row in rows} == {"d" * 64}
    assert {row["seed"] for row in rows} == {20260610}


def test_query_hash_matches_recording_layer(tmp_path: Path) -> None:
    """query_hash 必须与录制层 stable_hash(query) 同口径（防两套哈希打架）。"""
    result = _result(query="把影像重投影到 EPSG:4326")
    out = write_observations_jsonl(tmp_path / "obs.jsonl", (result,))
    row = _read_lines(out)[0]
    assert row["query_hash"] == stable_hash("把影像重投影到 EPSG:4326")


def test_latency_always_null_in_replay(tmp_path: Path) -> None:
    """replay 秒回不是真实延迟，latency_ms 恒 null（规划：禁止上报假延迟）。"""
    out = write_observations_jsonl(tmp_path / "obs.jsonl", (_result(),))
    assert _read_lines(out)[0]["latency_ms"] is None


# --- 边界：空 results / harness_error 行 -----------------------------------


def test_empty_results_writes_empty_file_no_crash(tmp_path: Path) -> None:
    out = write_observations_jsonl(tmp_path / "obs.jsonl", ())
    assert out.exists()
    assert out.read_text(encoding="utf-8") == ""
    assert _read_lines(out) == []


def test_harness_error_row_keeps_error_field(tmp_path: Path) -> None:
    err = _result(
        case_id="boom",
        correct=False,
        attribution="recording_or_harness_error",
        error="MissingRecordingError: no recording",
    )
    out = write_observations_jsonl(tmp_path / "obs.jsonl", (err,))
    row = _read_lines(out)[0]
    assert row["attribution"] == "recording_or_harness_error"
    assert row["error"] == "MissingRecordingError: no recording"
    assert row["correct"] is False


# --- 非法：None 字段安全序列化成 null，不抛 ---------------------------------


def test_none_fields_serialize_as_null(tmp_path: Path) -> None:
    none_result = _result(
        case_id="none_case",
        expected_action="none",
        expected_capability=None,
        actual_action="none",
        actual_capability=None,
        raw_action="none",
        raw_capability=None,
        correct=True,
    )
    out = write_observations_jsonl(tmp_path / "obs.jsonl", (none_result,))
    row = _read_lines(out)[0]
    assert row["expected"] == "none"  # expected_label 把 None 渲染成 "none"
    assert row["actual"] == "none"
    assert row["raw_capability"] is None  # 原始字段保持 null，不强转
    assert row["validation_error"] is None
    assert row["attribution"] is None


# --- 异常：目录不存在自动建 -------------------------------------------------


def test_creates_missing_parent_dir(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "reports"
    out = write_observations_jsonl(nested / "obs.jsonl", (_result(),))
    assert out.exists()
    assert nested.is_dir()


# --- 历史重复：run 级元数据默认空串/None，行级仍合法 ------------------------


def test_run_level_defaults_when_omitted(tmp_path: Path) -> None:
    """stress 不冻结、无 prompt_hash manifest：省略 run 级字段仍出合法行。"""
    out = write_observations_jsonl(tmp_path / "obs.jsonl", (_result(),), dataset="random-stress", seed=40010)
    row = _read_lines(out)[0]
    assert row["dataset"] == "random-stress"
    assert row["seed"] == 40010
    assert row["dataset_hash"] == ""
    assert row["prompt_hash"] == ""
    assert row["model"] == ""

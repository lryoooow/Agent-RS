"""Analyze planner prompt recordings without calling the live LLM.

This script is for prompt ablation reports. It replays historical recordings by
case id and context, so older prompt versions remain comparable after the current
prompt changes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

if __package__ in {None, ""}:
    backend_root = Path(__file__).resolve().parents[3]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

from tests.ai.eval.cases import GENERATED_CASES, PlannerEvalCase, validate_cases
from tests.ai.eval.clients import HistoricalReplayClient
from tests.ai.eval.harness import CaseResult, compute_grouped_metrics, default_eval_config, run_cases


BASELINE_EXPECTED = {
    "total": 308,
    "main_total": 278,
    "hard_negative_total": 90,
    "hard_negative_fp": 19,
    "diagnostic_total": 30,
    "diagnostic_fp": 24,
}


@dataclass(frozen=True)
class RunAnalysis:
    name: str
    recordings_dir: Path
    results: tuple[CaseResult, ...]


async def replay_historical_run(name: str, recordings_dir: Path, tmp_root: Path) -> RunAnalysis:
    model = _infer_recorded_model(recordings_dir)
    results = await run_cases(
        GENERATED_CASES,
        tmp_root=tmp_root / name,
        client_factory=lambda context: HistoricalReplayClient(recordings_dir, context),
        config=default_eval_config(model),
    )
    return RunAnalysis(name=name, recordings_dir=recordings_dir, results=results)


def assert_baseline_expected(analysis: RunAnalysis) -> None:
    grouped = compute_grouped_metrics(analysis.results)
    if len(analysis.results) != BASELINE_EXPECTED["total"]:
        raise AssertionError(f"baseline total mismatch: {len(analysis.results)}")
    if grouped["main"].total != BASELINE_EXPECTED["main_total"]:
        raise AssertionError(f"baseline main total mismatch: {grouped['main'].total}")
    if grouped["hard_negative"].total != BASELINE_EXPECTED["hard_negative_total"]:
        raise AssertionError(f"baseline hard_negative total mismatch: {grouped['hard_negative'].total}")
    if grouped["hard_negative"].fp != BASELINE_EXPECTED["hard_negative_fp"]:
        raise AssertionError(f"baseline hard_negative FP mismatch: {grouped['hard_negative'].fp}")
    if grouped["diagnostic_unsupported"].total != BASELINE_EXPECTED["diagnostic_total"]:
        raise AssertionError(
            f"baseline diagnostic_unsupported total mismatch: {grouped['diagnostic_unsupported'].total}"
        )
    if grouped["diagnostic_unsupported"].fp != BASELINE_EXPECTED["diagnostic_fp"]:
        raise AssertionError(f"baseline diagnostic_unsupported FP mismatch: {grouped['diagnostic_unsupported'].fp}")


def render_report(baseline: RunAnalysis, candidate: RunAnalysis | None = None) -> str:
    lines: list[str] = []
    lines.append("# Planner Prompt Dev-Set Analysis")
    lines.append("")
    lines.append("> 说明：本报告是 dev-set 分析，只说明当前 dev-set 题库上的表现，不代表泛化结论。")
    lines.append("> live 调用只用于录制 raw 输出；正式分数均来自 historical replay。")
    lines.append("")
    lines.extend(_run_summary_section(baseline, candidate))
    lines.extend(_hard_negative_section(baseline, title="Baseline hard_negative FP"))
    lines.extend(_diagnostic_section(baseline, title="Baseline diagnostic_unsupported"))
    if candidate is not None:
        lines.extend(_hard_negative_section(candidate, title=f"{candidate.name} hard_negative FP"))
        lines.extend(_diagnostic_section(candidate, title=f"{candidate.name} diagnostic_unsupported"))
        lines.extend(_comparison_section(baseline, candidate))
    return "\n".join(lines).rstrip() + "\n"


def _run_summary_section(baseline: RunAnalysis, candidate: RunAnalysis | None) -> list[str]:
    rows = [_summary_row(baseline)]
    if candidate is not None:
        rows.append(_summary_row(candidate))
    lines = ["## Summary", ""]
    lines.append("| run | main acc | main FP | main FN | positive acc | hard_negative FP | diagnostic FP |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    lines.extend(rows)
    lines.append("")
    return lines


def _summary_row(analysis: RunAnalysis) -> str:
    grouped = compute_grouped_metrics(analysis.results)
    return (
        f"| {analysis.name} | {_pct(grouped['main'].accuracy)} | {grouped['main'].fp} | "
        f"{grouped['main'].fn} | {_pct(grouped['generated_positive'].accuracy)} | "
        f"{grouped['hard_negative'].fp} | {grouped['diagnostic_unsupported'].fp} |"
    )


def _hard_negative_section(analysis: RunAnalysis, *, title: str) -> list[str]:
    failures = [
        result
        for result in analysis.results
        if result.source == "generated"
        and result.scoring == "main"
        and result.expected_action == "none"
        and result.actual_action == "call"
        and not result.prompt_near
    ]
    by_category = Counter(result.category for result in failures)
    by_capability = Counter(result.actual_label for result in failures)
    lines = [f"## {title}", ""]
    lines.append(f"- FP count: {len(failures)}")
    lines.append(f"- By category: {_counter_text(by_category)}")
    lines.append(f"- By actual capability: {_counter_text(by_capability)}")
    lines.append("")
    lines.append("| case_id | category | actual | attribution | selector/validator reason | query |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in failures:
        lines.append(
            "| "
            + " | ".join(
                [
                    item.case_id,
                    item.category,
                    item.actual_label,
                    item.attribution or "",
                    item.mismatch_reason or item.validation_error or "",
                    _table_text(item.query),
                ]
            )
            + " |"
        )
    lines.append("")
    return lines


def _diagnostic_section(analysis: RunAnalysis, *, title: str) -> list[str]:
    items = [
        result
        for result in analysis.results
        if result.scoring == "diagnostic_unsupported" and result.actual_action == "call"
    ]
    by_capability = Counter(result.actual_label for result in items)
    first_task_matches = sum(1 for result in items if result.actual_capability == _unsupported_first_task(result.case_id))
    lines = [f"## {title}", ""]
    lines.append(f"- Diagnostic FP count: {len(items)}")
    lines.append(f"- By selected capability: {_counter_text(by_capability)}")
    lines.append(f"- Selected first requested task: {first_task_matches}/{len(items)}")
    lines.append("")
    lines.append("| case_id | selected | first_requested_task | query |")
    lines.append("| --- | --- | --- | --- |")
    for item in items:
        lines.append(
            f"| {item.case_id} | {item.actual_label} | {_unsupported_first_task(item.case_id) or ''} | "
            f"{_table_text(item.query)} |"
        )
    lines.append("")
    return lines


def _comparison_section(baseline: RunAnalysis, candidate: RunAnalysis) -> list[str]:
    base = compute_grouped_metrics(baseline.results)
    cand = compute_grouped_metrics(candidate.results)
    lines = ["## Comparison", ""]
    lines.append("| metric | baseline | candidate | delta |")
    lines.append("| --- | ---: | ---: | ---: |")
    rows = (
        ("main accuracy", base["main"].accuracy, cand["main"].accuracy, True),
        ("main FP", base["main"].fp, cand["main"].fp, False),
        ("main FN", base["main"].fn, cand["main"].fn, False),
        ("generated_positive accuracy", base["generated_positive"].accuracy, cand["generated_positive"].accuracy, True),
        ("hard_negative FP", base["hard_negative"].fp, cand["hard_negative"].fp, False),
        ("diagnostic_unsupported FP", base["diagnostic_unsupported"].fp, cand["diagnostic_unsupported"].fp, False),
    )
    for name, left, right, is_pct in rows:
        if is_pct:
            lines.append(f"| {name} | {_pct(float(left))} | {_pct(float(right))} | {_pct(float(right) - float(left))} |")
        else:
            lines.append(f"| {name} | {left} | {right} | {int(right) - int(left)} |")
    lines.append("")
    return lines


def _unsupported_first_task(case_id: str) -> str | None:
    prefix = "gen_unsupported_multi_tool_"
    if not case_id.startswith(prefix):
        return None
    index = int(case_id.removeprefix(prefix))
    slot = (index - 1) % 5
    return (
        "calculate_ndvi",
        "cloud_shadow_mask",
        "clip_reproject_raster",
        "ocr_recognize",
        "render_band_composite",
    )[slot]


def _counter_text(counter: Counter[str]) -> str:
    if not counter:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(counter.items()))


def _table_text(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _infer_recorded_model(recordings_dir: Path) -> str:
    import json

    first = next(iter(sorted(recordings_dir.glob("*.json"))), None)
    if first is None:
        return "planner-eval-model"
    payload = json.loads(first.read_text(encoding="utf-8"))
    model = payload.get("model")
    return str(model) if model else "planner-eval-model"


async def _run(args: argparse.Namespace) -> int:
    validate_cases()
    baseline_dir = Path(args.baseline_recordings_dir)
    candidate_dir = Path(args.candidate_recordings_dir) if args.candidate_recordings_dir else None
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_parent = Path(args.tmp_dir)
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="planner_prompt_analysis_", dir=tmp_parent) as tmp:
        tmp_root = Path(tmp)
        baseline = await replay_historical_run(args.baseline_name, baseline_dir, tmp_root)
        if args.assert_baseline:
            assert_baseline_expected(baseline)
        candidate = None
        if candidate_dir is not None:
            candidate = await replay_historical_run(args.candidate_name, candidate_dir, tmp_root)
    output.write_text(render_report(baseline, candidate), encoding="utf-8")
    print(f"Wrote planner prompt analysis report: {output}")
    return 0


def main() -> int:
    default_output = (
        Path(__file__).resolve().parent
        / "reports"
        / f"planner_prompt_devset_analysis_{datetime.now().strftime('%Y%m%d')}.md"
    )
    parser = argparse.ArgumentParser(description="Analyze historical planner prompt recordings.")
    parser.add_argument("--baseline-recordings-dir", required=True)
    parser.add_argument("--candidate-recordings-dir", default=None)
    parser.add_argument("--baseline-name", default="baseline")
    parser.add_argument("--candidate-name", default="candidate")
    parser.add_argument("--output", default=str(default_output))
    parser.add_argument("--tmp-dir", default=str(Path.cwd() / ".tmp_planner_eval_runs"))
    parser.add_argument("--assert-baseline", action="store_true")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

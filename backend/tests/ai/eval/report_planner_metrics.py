"""LLM planner decision metrics report.

Run from backend/:
    python -m tests.ai.eval.report_planner_metrics
    python -m tests.ai.eval.report_planner_metrics --live
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
from pathlib import Path
from datetime import UTC, datetime

if __package__ in {None, ""}:
    backend_root = Path(__file__).resolve().parents[3]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

from app.agent.config import resolve_ai_config
from app.agent.provider import create_chat_client

from tests.ai.eval.cases import CI_REPLAY_CASES, EVAL_CASES, GENERATED_CASES, GOLDEN_CASES, validate_cases
from tests.ai.eval.clients import LiveRecordingClient, ReplayClient
from tests.ai.eval.harness import compute_grouped_metrics, compute_metrics, default_eval_config, run_cases


RECORDINGS_ROOT = Path(__file__).resolve().parent / "recordings"
DEFAULT_RECORDINGS_DIR = RECORDINGS_ROOT / "ci_subset"
LIVE_RUNS_DIR = RECORDINGS_ROOT / "live_runs"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _print_metrics(results) -> None:
    metrics = compute_metrics(results)
    print()
    print("=" * 80)
    print("LLM Planner Decision Metrics")
    print("=" * 80)
    print(f"样本量: {metrics.total}")
    print(f"有效样本: {metrics.valid_total}")
    print(f"正确: {metrics.correct}")
    print(f"准确率: {_pct(metrics.accuracy)}")
    print(f"FP 误触发: {metrics.fp}")
    print(f"FN 漏触发: {metrics.fn}")
    print(f"归因计数: {metrics.attribution_counts or '无'}")
    print()
    print("混淆矩阵（行=期望，列=实际）:")
    labels = sorted(set(metrics.confusion) | {label for row in metrics.confusion.values() for label in row})
    if labels:
        print("expected\\actual".ljust(32) + "".join(label[:24].ljust(26) for label in labels))
        for expected in labels:
            row = metrics.confusion.get(expected, {})
            line = expected[:30].ljust(32)
            for actual in labels:
                line += str(row.get(actual, 0)).ljust(26)
            print(line)
    else:
        print("无")
    if metrics.mismatches:
        print()
        print("失配明细:")
        for item in metrics.mismatches:
            print(
                f"- {item.case_id} | expected={item.expected_label} "
                f"actual={item.actual_label} attribution={item.attribution} "
                f"reason={item.mismatch_reason} | {item.query}"
            )
    else:
        print()
        print("失配明细: 无")
    print()
    print("分块指标:")
    for name, group_metrics in compute_grouped_metrics(results).items():
        if group_metrics.total == 0:
            continue
        print(
            f"- {name}: samples={group_metrics.total}, valid={group_metrics.valid_total}, "
            f"accuracy={_pct(group_metrics.accuracy)}, FP={group_metrics.fp}, FN={group_metrics.fn}"
        )


async def _run(args: argparse.Namespace) -> int:
    validate_cases()
    cases = _select_cases(args)
    recordings_dir = _recordings_dir_for_args(args)
    tmp_parent = Path(args.tmp_dir)
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="planner_eval_", dir=tmp_parent) as tmp:
        tmp_root = Path(tmp)
        if args.live:
            config = resolve_ai_config()
            base_client = create_chat_client(config)

            def factory(context):
                return LiveRecordingClient(base_client, recordings_dir, context)

        else:
            config = default_eval_config(args.model or _infer_recorded_model(recordings_dir))

            def factory(context):
                return ReplayClient(recordings_dir, context)

        results = await run_cases(
            cases,
            tmp_root=tmp_root,
            client_factory=factory,
            config=config,
            fail_on_harness_error=not args.keep_going,
        )
    _print_metrics(results)
    metrics = compute_metrics(results)
    if args.min_accuracy is not None and metrics.accuracy < args.min_accuracy:
        print(f"准确率低于阈值: {_pct(metrics.accuracy)} < {_pct(args.min_accuracy)}")
        return 1
    if args.require_zero_fp and metrics.fp:
        print(f"FP 必须为 0，当前为 {metrics.fp}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run LLM planner decision metrics.")
    parser.add_argument("--live", action="store_true", help="Call the configured live LLM and write recordings.")
    parser.add_argument("--recordings-dir", default=None)
    parser.add_argument(
        "--case-set",
        choices=("ci", "golden", "generated", "all"),
        default="ci",
        help="ci=replay subset, generated=300 generated cases, all=golden+generated.",
    )
    parser.add_argument("--full", action="store_true", help="Alias for --case-set all.")
    parser.add_argument("--run-tag", default=None, help="Live recordings subdirectory name.")
    parser.add_argument("--model", default=None, help="Replay-mode model name; defaults to recorded model.")
    parser.add_argument("--tmp-dir", default=str(Path.cwd() / ".tmp_planner_eval_runs"))
    parser.add_argument("--min-accuracy", type=float, default=None)
    parser.add_argument("--require-zero-fp", action="store_true")
    parser.add_argument("--keep-going", action="store_true", help="Collect harness errors instead of failing fast.")
    return asyncio.run(_run(parser.parse_args()))


def _select_cases(args: argparse.Namespace):
    if args.full:
        return EVAL_CASES
    if args.case_set == "ci":
        return CI_REPLAY_CASES
    if args.case_set == "golden":
        return GOLDEN_CASES
    if args.case_set == "generated":
        return GENERATED_CASES
    return EVAL_CASES


def _recordings_dir_for_args(args: argparse.Namespace) -> Path:
    if args.recordings_dir:
        return Path(args.recordings_dir)
    if args.live:
        tag = args.run_tag or datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ")
        return LIVE_RUNS_DIR / tag
    return DEFAULT_RECORDINGS_DIR


def _infer_recorded_model(recordings_dir: Path) -> str:
    import json

    first = next(iter(sorted(recordings_dir.glob("*.json"))), None)
    if first is None:
        return "planner-eval-model"
    payload = json.loads(first.read_text(encoding="utf-8"))
    model = payload.get("model")
    return str(model) if model else "planner-eval-model"


if __name__ == "__main__":
    raise SystemExit(main())

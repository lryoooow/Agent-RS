"""random-stress 运行入口：多 seed 现采现跑，看跨 seed 分布（均值/最差/方差）。

与 heldout 的纪律差异：
- 不冻结、不封存：每 seed 现生成现 live 跑，重点是分布稳定性，不是单次密封成绩。
- 录制落 recordings/stress_runs/<dataset>/<seed>/（gitignore），可断点续录。
- 报告输出每 seed 指标 + 跨 seed 聚合（mean / worst-seed / variance），绝不只报最好单次。

用法（backend/ 下，经 .local/heldout_runner.py bootstrap 或直接 -m）：
    python -m tests.ai.eval.run_stress live          # 三 seed 全量 live（3 seed × STRESS_TARGET=1000 = 3000 次调用）
    python -m tests.ai.eval.run_stress live --limit 20   # 每 seed 限量试跑
    python -m tests.ai.eval.run_stress score         # replay 已录制，出分布报告
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    backend_root = Path(__file__).resolve().parents[3]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

from tests.ai.eval.stress_generator import (
    STRESS_DATASET,
    STRESS_SEEDS,
    STRESS_TARGET,
    generate_stress_cases,
    stress_summary,
    validate_stress_cases,
)


EVAL_DIR = Path(__file__).resolve().parent
RUNS_DIR = EVAL_DIR / "recordings" / "stress_runs"
REPORTS_DIR = EVAL_DIR / "reports"


def _seed_dir(seed: int) -> Path:
    return RUNS_DIR / STRESS_DATASET / str(seed)


def _now_tag() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _recording_done(seed: int, case_id: str, query: str | None = None) -> bool:
    """录制是否有效完成。传 query 时额外校验 query_hash 同源——生成器一改、query 内容变了，
    旧录制 query_hash 不符即视为失效（返回 False 触发重录），根除"用旧 query 录制冒充新题"。"""
    path = _seed_dir(seed) / f"{case_id}.json"
    if not path.exists():
        return False
    if query is None:
        return True
    import json
    from tests.ai.eval.clients import stable_hash
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False  # 录制损坏，重录
    return rec.get("query_hash") == stable_hash(query)


async def _record_seed(seed: int, limit: int, shard: tuple[int, int] | None = None) -> int:
    from app.agent.config import resolve_ai_config
    from app.agent.provider import create_chat_client
    from tests.ai.eval.clients import LiveRecordingClient
    from tests.ai.eval.harness import build_recording_context, run_cases, _request_for_case

    cases = generate_stress_cases(seed=seed, target=STRESS_TARGET)
    validate_stress_cases(cases)
    config = resolve_ai_config()
    seed_dir = _seed_dir(seed)
    seed_dir.mkdir(parents=True, exist_ok=True)

    pending = tuple(c for c in cases if not _recording_done(seed, c.case_id, c.query))
    # 分片：步长切片不重叠（shard i of n 取 index%n==i），多进程并行各跑各的、互不抢同一 case。
    if shard is not None:
        idx, total = shard
        pending = tuple(c for n, c in enumerate(pending) if n % total == idx)
        print(f"seed {seed} shard {idx}/{total}: {len(pending)} pending in this shard")
    else:
        print(f"seed {seed}: {len(cases) - len(pending)} recorded, {len(pending)} pending")
    if not pending:
        return 0
    if limit:
        pending = pending[:limit]
        print(f"  limited to {len(pending)} this invocation")

    base_client = create_chat_client(config)

    def factory(context):
        return LiveRecordingClient(base_client, seed_dir, context)

    tmp_parent = Path.cwd() / ".tmp_planner_eval_runs"
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"stress_{seed}_", dir=tmp_parent) as tmp:
        results = await run_cases(
            pending,
            tmp_root=Path(tmp),
            client_factory=factory,
            config=config,
            fail_on_harness_error=False,
        )
    errors = [r for r in results if r.error]
    print(f"  recorded {len(results) - len(errors)} ok, {len(errors)} errors")
    if errors:
        for item in errors[:5]:
            print(f"    ERROR {item.case_id}: {item.error}")
    return 1 if errors else 0


def _seed_metrics(results) -> dict[str, float | int]:
    """单 seed 决策指标（与 heldout score 同口径，但不门控、只观测分布）。"""

    main = [r for r in results if r.scoring == "main" and not r.prompt_near and not r.error]
    valid = [r for r in results if not r.error]
    correct = sum(1 for r in main if r.correct)
    hard_neg = [r for r in main if r.expected_action == "none"]
    positives = [r for r in main if r.expected_action == "call"]
    hn_fp = [r for r in hard_neg if r.actual_action == "call"]
    pos_fn = [r for r in positives if r.actual_action == "none"]
    invalid = [r for r in results if r.planner_invalid]
    return {
        "samples": len(results),
        "valid": len(valid),
        "main": len(main),
        "accuracy": round(correct / len(main), 4) if main else 0.0,
        "hard_neg": len(hard_neg),
        "hn_fp": len(hn_fp),
        "hn_fp_rate": round(len(hn_fp) / len(hard_neg), 4) if hard_neg else 0.0,
        "positive": len(positives),
        "pos_fn": len(pos_fn),
        "pos_recall": round(1 - len(pos_fn) / len(positives), 4) if positives else 0.0,
        "planner_invalid": len(invalid),
        "harness_error": len(results) - len(valid),
    }


async def _score_seed(seed: int) -> tuple[dict, list]:
    from tests.ai.eval.clients import HistoricalReplayClient
    from tests.ai.eval.harness import default_eval_config, run_cases

    cases = generate_stress_cases(seed=seed, target=STRESS_TARGET)
    validate_stress_cases(cases)
    from app.agent.config import resolve_ai_config

    model = resolve_ai_config().model
    config = default_eval_config(model)
    seed_dir = _seed_dir(seed)

    # 只 score 已录制的 case：断点续录中途看分布时，未录条不当 harness_error 污染。
    # 全量录满 1000 后 cases 与录制一一对应，此过滤为恒等，口径不变。
    cases = tuple(c for c in cases if _recording_done(seed, c.case_id))

    def factory(context):
        return HistoricalReplayClient(seed_dir, context)

    tmp_parent = Path.cwd() / ".tmp_planner_eval_runs"
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"stress_score_{seed}_", dir=tmp_parent) as tmp:
        results = await run_cases(
            cases, tmp_root=Path(tmp), client_factory=factory, config=config,
            fail_on_harness_error=False,
        )
    return _seed_metrics(results), list(results)


def _aggregate(per_seed: dict[int, dict]) -> dict[str, dict]:
    """跨 seed 聚合：mean / worst-seed / stdev。worst 取对结论最不利的方向。"""

    def agg(metric: str, worst: str) -> dict:
        vals = [m[metric] for m in per_seed.values()]
        worst_val = min(vals) if worst == "min" else max(vals)
        return {
            "mean": round(statistics.fmean(vals), 4),
            "worst": worst_val,
            "stdev": round(statistics.pstdev(vals), 4) if len(vals) > 1 else 0.0,
            "per_seed": {str(s): per_seed[s][metric] for s in per_seed},
        }

    return {
        "accuracy": agg("accuracy", "min"),
        "hn_fp_rate": agg("hn_fp_rate", "max"),
        "pos_recall": agg("pos_recall", "min"),
        "planner_invalid": agg("planner_invalid", "max"),
        "harness_error": agg("harness_error", "max"),
    }


async def _score(args) -> int:
    from tests.ai.eval.harness import write_observations_jsonl

    per_seed: dict[int, dict] = {}
    all_mismatches: list = []
    for seed in STRESS_SEEDS:
        if not _seed_dir(seed).exists():
            print(f"seed {seed}: no recordings, skip (run `live` first)")
            continue
        metrics, results = await _score_seed(seed)
        per_seed[seed] = metrics
        print(f"seed {seed}: acc={metrics['accuracy']} hn_fp={metrics['hn_fp_rate']} "
              f"recall={metrics['pos_recall']} invalid={metrics['planner_invalid']} "
              f"harness_err={metrics['harness_error']}")
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        write_observations_jsonl(
            REPORTS_DIR / f"stress_observations_{seed}_{_now_tag()}.jsonl",
            tuple(results),
            dataset=STRESS_DATASET,
            seed=seed,
        )
        for r in results:
            if not r.correct and r.attribution != "recording_or_harness_error":
                all_mismatches.append((seed, r))
    if not per_seed:
        print("no seed recordings found; run `live` first")
        return 1

    agg = _aggregate(per_seed)
    report = {
        "dataset": STRESS_DATASET,
        "seeds": list(per_seed),
        "target_per_seed": STRESS_TARGET,
        "scored_at": datetime.now(UTC).isoformat(),
        "per_seed": {str(s): per_seed[s] for s in per_seed},
        "aggregate": agg,
    }
    print("\n=== 跨 seed 聚合（mean / worst-seed / stdev）===")
    print(json.dumps(agg, ensure_ascii=False, indent=2))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"stress_score_{_now_tag()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    mism = REPORTS_DIR / f"stress_mismatches_{_now_tag()}.md"
    lines = ["# random-stress 失配明细（跨 seed，看分布不门控）", "",
             "| seed | case_id | category | expected | actual | attribution | reason |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for seed, r in all_mismatches:
        lines.append(f"| {seed} | {r.case_id} | {r.category} | {r.expected_label} "
                     f"| {r.actual_label} | {r.attribution} | {r.mismatch_reason} |")
    mism.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nscore report: {out}")
    print(f"mismatch report: {mism} ({len(all_mismatches)} mismatches across seeds)")
    return 0


async def _live(args) -> int:
    rc = 0
    seeds = [args.seed] if args.seed else list(STRESS_SEEDS)
    shard = None
    if args.shard:
        idx, total = (int(x) for x in args.shard.split("/"))
        if not (0 <= idx < total):
            raise SystemExit(f"--shard {args.shard} 非法：需 0 <= i < n")
        shard = (idx, total)
    for seed in seeds:
        rc |= await _record_seed(seed, args.limit, shard)
    if rc:
        print("\nsome seeds had errors; rerun `live` to resume (断点续录)")
    else:
        print("\nall seeds recorded; run `score` next")
    return rc


def main() -> int:
    parser = argparse.ArgumentParser(description="random-stress live/score")
    sub = parser.add_subparsers(dest="command", required=True)
    live = sub.add_parser("live")
    live.add_argument("--limit", type=int, default=0)
    live.add_argument("--seed", type=int, default=0, help="只跑单个 seed（多进程并行用）")
    live.add_argument("--shard", type=str, default="", help="seed 内分片 i/n，步长不重叠（多进程并行用）")
    sub.add_parser("score")
    args = parser.parse_args()
    if args.command == "live":
        return asyncio.run(_live(args))
    return asyncio.run(_score(args))


if __name__ == "__main__":
    raise SystemExit(main())

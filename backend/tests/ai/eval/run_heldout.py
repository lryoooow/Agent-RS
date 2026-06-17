"""heldout-v1 冻结与评分入口。

用法（backend/ 下）：
    python -m tests.ai.eval.run_heldout freeze         # 生成+冻结+抽检报告（不跑模型）
    python -m tests.ai.eval.run_heldout live           # 唯一一次 live 录制（断点续录）
    python -m tests.ai.eval.run_heldout seal           # 录制齐全后封存
    python -m tests.ai.eval.run_heldout score          # sealed replay 出正式成绩
    python -m tests.ai.eval.run_heldout score --gate   # 附带阈值门（提前写死）

纪律：freeze 幂等且拒绝改题重冻结；live 只认 in_progress 且 pin 一致；seal 后重 live 报错；
score 只接受 sealed run，且重算 dataset hash + recordings digest。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

if __package__ in {None, ""}:
    backend_root = Path(__file__).resolve().parents[3]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

from tests.ai.eval.heldout_generator import (
    HELDOUT_DATASET,
    HELDOUT_V1_SEED,
    HELDOUT_V2_DATASET,
    HELDOUT_V2_SEED,
    HELDOUT_V3_DATASET,
    HELDOUT_V3_SEED,
    HELDOUT_V4_DATASET,
    HELDOUT_V4_SEED,
    dataset_hash,
    generate_heldout_cases,
    heldout_summary,
)
from tests.ai.eval.heldout_manifest import (
    assert_dataset_frozen,
    assert_run_sealed,
    freeze_dataset,
    load_dataset_manifest,
    prepare_live_run,
    seal_run,
)


EVAL_DIR = Path(__file__).resolve().parent
REPORTS_DIR = EVAL_DIR / "reports"

# 版本可配：默认 v1（历史证据，路径不变）；--version v2 切到 heldout-v2 全新 seed/目录。
# 这些全局由 _configure_version() 在 main 解析参数后设置，各 cmd 统一读它们。
_VERSIONS = {
    "v1": {"dataset": HELDOUT_DATASET, "seed": HELDOUT_V1_SEED, "dirname": "heldout_v1"},
    "v2": {"dataset": HELDOUT_V2_DATASET, "seed": HELDOUT_V2_SEED, "dirname": "heldout_v2"},
    "v3": {"dataset": HELDOUT_V3_DATASET, "seed": HELDOUT_V3_SEED, "dirname": "heldout_v3"},
    "v4": {"dataset": HELDOUT_V4_DATASET, "seed": HELDOUT_V4_SEED, "dirname": "heldout_v4"},
}
DATASET = HELDOUT_DATASET
SEED = HELDOUT_V1_SEED
FROZEN_DIR = EVAL_DIR / "recordings" / "heldout_v1"
RUN_DIR = FROZEN_DIR / "live_run"


def _configure_version(version: str) -> None:
    global DATASET, SEED, FROZEN_DIR, RUN_DIR
    cfg = _VERSIONS[version]
    DATASET = cfg["dataset"]
    SEED = cfg["seed"]
    FROZEN_DIR = EVAL_DIR / "recordings" / cfg["dirname"]
    RUN_DIR = FROZEN_DIR / "live_run"

# 提前写死的验收阈值（目标门槛，非首跑预测；不许事后改）。
GATES = {
    "main_accuracy_min": 0.90,
    "hard_negative_fp_rate_max": 0.05,
    "positive_recall_min": 0.95,
    "hallucinated_id_max": 0,
    "non_owner_bypass_max": 0,
    "planner_invalid_rate_max": 0.01,
}

_SAMPLE_RATIO = 0.125  # 每个 category 分层抽 12.5%，至少 1 条（避免步长与生成轮转周期共振造成子类盲区）


def _now_tag() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def _stratified_sample(cases) -> list[int]:
    """按 category 分层、seed 确定性随机抽样：每子类 max(1, round(12.5%)) 条，无盲区。"""

    from collections import defaultdict
    from random import Random

    rng = Random(SEED + 1)  # 与生成流独立的抽样流
    by_category: dict[str, list[int]] = defaultdict(list)
    for idx, case in enumerate(cases):
        by_category[case.category].append(idx)
    picked: list[int] = []
    for category in sorted(by_category):
        indices = by_category[category]
        k = max(1, round(len(indices) * _SAMPLE_RATIO))
        picked.extend(rng.sample(indices, k))
    return sorted(picked)


def cmd_freeze() -> int:
    cases = generate_heldout_cases(seed=SEED, dataset=DATASET)
    manifest_path = freeze_dataset(
        cases,
        dataset_id=DATASET,
        seed=SEED,
        out_dir=FROZEN_DIR,
        label_policy="rule-derived(derive_label)+manual-stratified-spot-check-12.5%",
    )
    summary = heldout_summary(cases)
    print(f"frozen manifest: {manifest_path}")
    print(json.dumps({k: v for k, v in summary.items() if k != "subtypes"}, ensure_ascii=False, indent=2))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = REPORTS_DIR / f"{DATASET.replace('-', '_')}_spotcheck_{_now_tag()}.md"
    sample = _stratified_sample(cases)
    lines = [
        f"# {DATASET} 人工抽检报告（分层抽样，每 category 12.5%）",
        "",
        f"- dataset_hash: `{dataset_hash(cases)}`",
        f"- seed: {SEED}  case_count: {len(cases)}  sampled: {len(sample)}",
        "- 抽样：按 category 分层、seed 确定性随机，每子类至少 1 条——任何子类都不会成为盲区。",
        "- 检查点：①表达无歧义 ②场景合理 ③label 与场景一致。",
        "- 纪律：发现错标不许单条改题；整体废弃本数据集（删除冻结目录——它尚未运行），换新 seed 重新生成冻结。",
        "",
        "| # | case_id | expected | query |",
        "| --- | --- | --- | --- |",
    ]
    for idx in sample:
        case = cases[idx]
        expected = case.expected_capability or "none"
        query = case.query.replace("|", "\\|")
        lines.append(f"| {idx} | {case.case_id} | {expected} | {query} |")
    lines += ["", "## 人工结论", "", "- [ ] 抽检通过，冻结生效", "- [ ] 发现错标（列出 case_id，废弃数据集换 seed 重生成）", ""]
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"spot-check report: {report} (sampled {len(sample)})")
    return 0


def _recording_done(case_id: str) -> bool:
    return (RUN_DIR / f"{case_id}.json").exists()


async def _live(args: argparse.Namespace) -> int:
    from app.agent.config import resolve_ai_config
    from app.agent.provider import create_chat_client
    from tests.ai.eval.clients import LiveRecordingClient
    from tests.ai.eval.harness import build_recording_context, run_cases, _request_for_case

    cases = generate_heldout_cases(seed=SEED, dataset=DATASET)
    manifest = assert_dataset_frozen(cases, FROZEN_DIR)
    config = resolve_ai_config()

    # prompt_hash 取自当前 prompt（live 前先算，用于 run pin）。
    sample_context = None
    from tests.ai.eval.harness import default_eval_config  # noqa: F401

    # 用首条 case 构建 context 拿 prompt_hash（与录制层一致的计算方式）。
    import os
    from tests.ai.eval.harness import _patched_env, _write_imagery_fixtures
    from app.agent.search.cache import get_planner_decision_cache
    from app.core.settings import get_settings

    with tempfile.TemporaryDirectory(prefix="heldout_pin_") as tmp:
        imagery_root = Path(tmp) / "imagery"
        imagery_root.mkdir(parents=True)
        _write_imagery_fixtures(imagery_root, cases[0])
        with _patched_env(
            {
                "DATABASE_ENABLED": "false",
                "IMAGERY_UPLOAD_DIR": str(imagery_root),
                "TAVILY_API_KEY": os.environ.get("TAVILY_API_KEY") or "planner-eval-tavily-key",
                "AGENT_WEB_SEARCH_MAX_CALLS": "3",
            }
        ):
            get_settings.cache_clear()
            get_planner_decision_cache().clear()
            sample_context = build_recording_context(
                cases[0], request=_request_for_case(cases[0]), config=config
            )
    prompt_hash = sample_context.prompt_hash

    run_manifest = prepare_live_run(
        RUN_DIR,
        dataset_id=manifest["dataset_id"],
        dataset_hash=manifest["dataset_hash"],
        prompt_hash=prompt_hash,
        model=config.model,
    )
    pending = tuple(case for case in cases if not _recording_done(case.case_id))
    print(f"run {run_manifest['run_id']}: {len(cases) - len(pending)} recorded, {len(pending)} pending")
    if not pending:
        print("nothing to record; run `seal` next")
        return 0
    if args.limit:
        pending = pending[: args.limit]
        print(f"limited to {len(pending)} cases this invocation")

    base_client = create_chat_client(config)

    def factory(context):
        return LiveRecordingClient(base_client, RUN_DIR, context)

    tmp_parent = Path.cwd() / ".tmp_planner_eval_runs"
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="heldout_live_", dir=tmp_parent) as tmp:
        results = await run_cases(
            pending,
            tmp_root=Path(tmp),
            client_factory=factory,
            config=config,
            fail_on_harness_error=False,
        )
    errors = [r for r in results if r.error]
    print(f"recorded {len(results) - len(errors)} ok, {len(errors)} errors")
    if errors:
        for item in errors[:10]:
            print(f"  ERROR {item.case_id}: {item.error}")
        print("rerun `live` to resume missing cases (断点续录)")
        return 1
    print("all pending recorded; run `seal` next")
    return 0


def cmd_seal() -> int:
    cases = generate_heldout_cases(seed=SEED, dataset=DATASET)
    assert_dataset_frozen(cases, FROZEN_DIR)
    manifest = seal_run(RUN_DIR, expected_case_ids=[case.case_id for case in cases])
    print(f"sealed: {manifest['run_id']}")
    print(f"recordings_hash: {manifest['recordings_hash']}")
    return 0


async def _score(args: argparse.Namespace) -> int:
    from tests.ai.eval.clients import HistoricalReplayClient
    from tests.ai.eval.harness import (
        compute_grouped_metrics,
        compute_metrics,
        default_eval_config,
        run_cases,
        write_observations_jsonl,
    )

    cases = generate_heldout_cases(seed=SEED, dataset=DATASET)
    dataset_manifest = assert_dataset_frozen(cases, FROZEN_DIR)
    run_manifest = assert_run_sealed(RUN_DIR)
    config = default_eval_config(run_manifest["model"])

    def factory(context):
        return HistoricalReplayClient(RUN_DIR, context)

    tmp_parent = Path.cwd() / ".tmp_planner_eval_runs"
    tmp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="heldout_score_", dir=tmp_parent) as tmp:
        results = await run_cases(
            cases,
            tmp_root=Path(tmp),
            client_factory=factory,
            config=config,
            fail_on_harness_error=False,
        )

    grouped = compute_grouped_metrics(results)
    overall = compute_metrics(results)

    # 决策质量专项统计。
    main_results = [r for r in results if r.scoring == "main" and not r.prompt_near]
    hard_neg = [r for r in main_results if r.expected_action == "none"]
    positives = [r for r in main_results if r.expected_action == "call"]
    hn_fp = [r for r in hard_neg if r.actual_action == "call"]
    pos_fn = [r for r in positives if r.actual_action == "none"]
    pos_wrong = [r for r in positives if r.actual_action == "call" and not r.correct]

    # 幻觉 ID：actual imagery/document id 不在该 case 的可用清单/期望集合里。
    halluc = []
    owned_lookup = {
        r.case_id: {item.imagery_id for item in c.imagery_inventory}
        for c, r in zip(cases, results)
        if c.case_id == r.case_id
    }
    expected_doc = {
        c.case_id: str(c.expected_arguments_subset.get("document_id", "")) for c in cases
    }
    for r in results:
        if r.actual_action != "call":
            continue
        img = str(r.actual_arguments.get("imagery_id") or "")
        doc = str(r.actual_arguments.get("document_id") or "")
        if img and img not in owned_lookup.get(r.case_id, set()):
            halluc.append((r.case_id, "imagery_id", img))
        if doc and doc != expected_doc.get(r.case_id, "") and not expected_doc.get(r.case_id):
            halluc.append((r.case_id, "document_id", doc))

    # 非属主绕过：non_owner 用例最终 action=call 即绕过（validator 没拦住）。
    non_owner_bypass = [
        r
        for c, r in zip(cases, results)
        if "non_owner" in c.category and r.actual_action == "call"
    ]
    # 输出解析最终失败（多次重试后仍 invalid，被降级 none）。
    invalid_results = [r for r in results if r.planner_invalid]

    main_acc = grouped["main"].accuracy
    hn_fp_rate = len(hn_fp) / len(hard_neg) if hard_neg else 0.0
    pos_recall = 1 - (len(pos_fn) / len(positives)) if positives else 0.0
    invalid_rate = len(invalid_results) / len(results) if results else 0.0

    report = {
        "dataset": dataset_manifest["dataset_id"],
        "dataset_hash": dataset_manifest["dataset_hash"],
        "run_id": run_manifest["run_id"],
        "prompt_hash": run_manifest["prompt_hash"],
        "model": run_manifest["model"],
        "scored_at": datetime.now(UTC).isoformat(),
        "totals": {"all": overall.total, "valid": overall.valid_total},
        "main": {
            "samples": grouped["main"].total,
            "accuracy": round(main_acc, 4),
            "fp": grouped["main"].fp,
            "fn": grouped["main"].fn,
        },
        "hard_negative": {
            "samples": len(hard_neg),
            "fp": len(hn_fp),
            "fp_rate": round(hn_fp_rate, 4),
        },
        "positive": {
            "samples": len(positives),
            "fn": len(pos_fn),
            "wrong_capability_or_args": len(pos_wrong),
            "recall": round(pos_recall, 4),
        },
        "diagnostic_unsupported": {
            "samples": grouped["diagnostic_unsupported"].total,
            "fp": grouped["diagnostic_unsupported"].fp,
        },
        "prompt_near_excluded": grouped["prompt_near"].total,
        "hallucinated_ids": len(halluc),
        "non_owner_bypass": len(non_owner_bypass),
        "planner_invalid": {"count": len(invalid_results), "rate": round(invalid_rate, 4)},
        "attribution": overall.attribution_counts,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"{DATASET.replace('-', '_')}_score_{_now_tag()}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    mism_path = REPORTS_DIR / f"{DATASET.replace('-', '_')}_mismatches_{_now_tag()}.md"
    lines = [
        f"# {DATASET} 失配明细（按类别聚合）",
        "",
        f"run: `{run_manifest['run_id']}`  dataset: `{dataset_manifest['dataset_hash'][:12]}…`",
        "",
        "| case_id | category | expected | actual | attribution | reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if r.correct or r.attribution == "recording_or_harness_error":
            continue
        lines.append(
            f"| {r.case_id} | {r.category} | {r.expected_label} | {r.actual_label} "
            f"| {r.attribution} | {r.mismatch_reason} |"
        )
    harness_err = [r for r in results if r.attribution == "recording_or_harness_error"]
    if harness_err:
        lines += ["", f"## harness/recording 错误（不计分）: {len(harness_err)}", ""]
        for r in harness_err[:20]:
            lines.append(f"- {r.case_id}: {r.error}")
    mism_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"score report: {out}")
    print(f"mismatch report: {mism_path}")

    obs_path = REPORTS_DIR / f"{DATASET.replace('-', '_')}_observations_{_now_tag()}.jsonl"
    write_observations_jsonl(
        obs_path,
        tuple(results),
        dataset=dataset_manifest["dataset_id"],
        dataset_hash=dataset_manifest["dataset_hash"],
        prompt_hash=run_manifest["prompt_hash"],
        model=run_manifest["model"],
        seed=SEED,
    )
    print(f"observations jsonl: {obs_path}")

    if args.gate:
        failures = []
        if main_acc < GATES["main_accuracy_min"]:
            failures.append(f"main accuracy {main_acc:.4f} < {GATES['main_accuracy_min']}")
        if hn_fp_rate > GATES["hard_negative_fp_rate_max"]:
            failures.append(f"hard_negative FP rate {hn_fp_rate:.4f} > {GATES['hard_negative_fp_rate_max']}")
        if pos_recall < GATES["positive_recall_min"]:
            failures.append(f"positive recall {pos_recall:.4f} < {GATES['positive_recall_min']}")
        if len(halluc) > GATES["hallucinated_id_max"]:
            failures.append(f"hallucinated ids {len(halluc)} > {GATES['hallucinated_id_max']}")
        if len(non_owner_bypass) > GATES["non_owner_bypass_max"]:
            failures.append(f"non-owner bypass {len(non_owner_bypass)} > {GATES['non_owner_bypass_max']}")
        if invalid_rate > GATES["planner_invalid_rate_max"]:
            failures.append(f"planner invalid rate {invalid_rate:.4f} > {GATES['planner_invalid_rate_max']}")
        if failures:
            print("\nGATE FAILED（首跑低分是有效信号，按纪律：失败样本复制进 dev-set 修，下一轮用 heldout-v2）:")
            for item in failures:
                print(f"  - {item}")
            return 1
        print("\nGATE PASSED")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="heldout freeze/live/seal/score（--version v1|v2）")
    parser.add_argument("--version", choices=("v1", "v2", "v3", "v4"), default="v1",
                        help="数据集版本：v1=历史证据(默认)，v2=修正口径后全新冻结盲测")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    live = sub.add_parser("live")
    live.add_argument("--limit", type=int, default=0, help="本次最多录制条数（成本控制，断点续录）")
    sub.add_parser("seal")
    score = sub.add_parser("score")
    score.add_argument("--gate", action="store_true")
    args = parser.parse_args()
    _configure_version(args.version)
    print(f"[heldout {args.version}] dataset={DATASET} seed={SEED} dir={FROZEN_DIR.name}")
    if args.command == "freeze":
        return cmd_freeze()
    if args.command == "live":
        return asyncio.run(_live(args))
    if args.command == "seal":
        return cmd_seal()
    return asyncio.run(_score(args))


if __name__ == "__main__":
    raise SystemExit(main())

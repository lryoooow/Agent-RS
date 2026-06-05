"""A/B 层确定性触发指标报告（独立脚本，非 pytest）。

作用：pytest 默认只输出 "N passed"，不显示任何数字。本脚本把混淆矩阵、
准确率、误触发率(FP)、漏触发率(FN) 等真实指标打印出来——无论通过与否都打印，
让"测试结果"从"通过/失败"变成"可量化的指标表"。

运行：
    python -m tests.ai.report_metrics        # 在 backend/ 目录下
    python backend/tests/ai/report_metrics.py # 在项目根目录下（自动补 sys.path）
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许从项目根直接运行：把 backend/ 补进 import 路径
_BACKEND = Path(__file__).resolve().parents[2]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.agent.router import RequestRoute, classify_request_route
from app.agent.prompting.scenarios import wants_ndvi_calculation
from app.agent.search.classifier import SearchIntent, classify_search_intent
from app.schemas.chat import ChatRequest

from tests.ai._trigger_cases import (
    NDVI_TEXT_CASES,
    ROUTE_CASES,
    ROUTING_RISK_CASES,
    SEARCH_INTENT_CASES,
)


def _request(query: str, *, use_memory: bool = False, use_rag: bool = False) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": query}],
        use_memory=use_memory,
        use_rag=use_rag,
    )


def _pct(num: int, den: int) -> str:
    if den == 0:
        return "n/a"
    return f"{num / den * 100:.1f}%"


def _section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def report_binary(
    title: str,
    rows: list[tuple[str, str, bool, bool]],
    positive_label: str,
    negative_label: str,
) -> None:
    """二分类指标：每行 (case_id, query, expected_positive, actual_positive)。

    positive = "应该触发"（进工具/联网/计算）。
    FP = 不该触发却触发了（误触发）。
    FN = 该触发却没触发（漏触发）。
    """
    _section(title)
    tp = fp = tn = fn = 0
    mismatches: list[tuple[str, str, bool, bool]] = []
    for case_id, query, expected, actual in rows:
        if expected and actual:
            tp += 1
        elif expected and not actual:
            fn += 1
            mismatches.append((case_id, query, expected, actual))
        elif not expected and actual:
            fp += 1
            mismatches.append((case_id, query, expected, actual))
        else:
            tn += 1

    total = tp + fp + tn + fn
    correct = tp + tn
    print(f"样本量: {total}  |  正确: {correct}  准确率: {_pct(correct, total)}")
    print(f"混淆矩阵（positive = {positive_label}）:")
    print(f"  TP 正确触发 : {tp}")
    print(f"  TN 正确跳过 : {tn}")
    print(f"  FP 误触发   : {fp}   误触发率: {_pct(fp, fp + tn)}")
    print(f"  FN 漏触发   : {fn}   漏触发率: {_pct(fn, fn + tp)}")
    if mismatches:
        print("  失配明细 (case_id | 预期 | 实际 | query):")
        for case_id, query, expected, actual in mismatches:
            exp = positive_label if expected else negative_label
            act = positive_label if actual else negative_label
            print(f"    {case_id} | {exp} | {act} | {query}")
    else:
        print("  失配明细: 无")


def report_multiclass(
    title: str,
    rows: list[tuple[str, str, object, object]],
    labels: list[object],
) -> None:
    """多分类指标：每行 (case_id, query, expected, actual)。打印准确率 + 混淆矩阵。"""
    _section(title)
    total = len(rows)
    correct = sum(1 for _, _, e, a in rows if e == a)
    print(f"样本量: {total}  |  正确: {correct}  准确率: {_pct(correct, total)}")
    # 混淆矩阵：行=预期 列=实际
    counts: dict[tuple[object, object], int] = {}
    for _, _, e, a in rows:
        counts[(e, a)] = counts.get((e, a), 0) + 1
    label_names = [getattr(lbl, "name", str(lbl)) for lbl in labels]
    header = "预期\\实际".ljust(14) + "".join(n.ljust(12) for n in label_names)
    print(header)
    for e in labels:
        line = getattr(e, "name", str(e)).ljust(14)
        for a in labels:
            line += str(counts.get((e, a), 0)).ljust(12)
        print(line)
    mismatches = [(cid, q, e, a) for cid, q, e, a in rows if e != a]
    if mismatches:
        print("失配明细 (case_id | 预期 | 实际 | query):")
        for cid, q, e, a in mismatches:
            en = getattr(e, "name", str(e))
            an = getattr(a, "name", str(a))
            print(f"  {cid} | {en} | {an} | {q}")
    else:
        print("失配明细: 无")


def main() -> None:
    # 1. 路由分类（多分类：DIRECT_CHAT vs FULL_PIPELINE）
    route_rows: list[tuple[str, str, object, object]] = []
    for case in (*ROUTE_CASES, *ROUTING_RISK_CASES):
        actual = classify_request_route(
            case.query,
            _request(case.query, use_memory=case.use_memory, use_rag=case.use_rag),
        )
        route_rows.append((case.case_id, case.query, case.expected, actual))
    report_multiclass(
        "路由分类指标 (router.classify_request_route)",
        route_rows,
        [RequestRoute.DIRECT_CHAT, RequestRoute.FULL_PIPELINE],
    )

    # 2. NDVI 计算意图（二分类：要计算 vs 不计算）
    ndvi_rows: list[tuple[str, str, bool, bool]] = []
    for case in NDVI_TEXT_CASES:
        actual = wants_ndvi_calculation(case.query)
        ndvi_rows.append((case.case_id, case.query, case.wants_calculation, bool(actual)))
    report_binary(
        "NDVI 计算意图指标 (scenarios.wants_ndvi_calculation)",
        ndvi_rows,
        positive_label="计算",
        negative_label="不计算",
    )

    # 3. 搜索意图（多分类：SKIP / FORCE / UNCERTAIN）
    search_rows: list[tuple[str, str, object, object]] = []
    for case in SEARCH_INTENT_CASES:
        messages = case.messages or [{"role": "user", "content": case.query}]
        actual = classify_search_intent(case.query, messages)
        search_rows.append((case.case_id, case.query, case.expected, actual))
    report_multiclass(
        "搜索意图指标 (web_search.classify_search_intent)",
        search_rows,
        [SearchIntent.SKIP, SearchIntent.FORCE, SearchIntent.UNCERTAIN],
    )

    print()
    print("说明：A/B 层为确定性规则，准确率应为 100%。任何 FP/FN/失配都是真实")
    print("规则缺陷或预期变更，需按根因定位处理，而非调阈值放过。")


if __name__ == "__main__":
    main()

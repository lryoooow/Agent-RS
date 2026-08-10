"""决策管线一致性：与模型判断力无关，只测「规划输出 → 已校验决策」这段管线。

## 为什么要这一层

现有的 replay 评测（test_planner_accuracy.py）把模型吐的**原始 JSON 文本**存成录制，
它同时耦合了两件事：模型判断得对不对（准确率），以及管线处理得对不对（一致性）。

这带来两个问题：

1. **录制会因为无关改动而失效。** 加一个 `generate_report` 能力就改了 planner prompt，
   `prompt_hash` 一变全部录制作废——这正是仓库当前 2 个失败测试的成因。
2. **迁到 AutoGen 后录制彻底不可用。** function calling 下模型发的是 `tool_calls`，
   没有 JSON 文本可回放。

本文件把「管线一致性」单独拆出来，用**确定性的规范输出**驱动，因此：

- 不需要 API key，不花钱，毫秒级；
- 加能力、改 prompt 都不会让它失效；
- 迁到 AutoGen 后，同一批期望可以原样跑在新管线上，成为**跨引擎的对比标尺**。

## 它到底测了什么

喂进「模型本应给出的规范答案」，断言管线产出对应的已校验决策。中间真实经过：

- `_parse_json_object` —— JSON 解析与容错
- `PlanValidator` —— 路由白名单（`route.candidate_tools`）、参数模型校验
- `tool_guards.validate_tool_access` —— 资源归属鉴权
- `TaskSelection` —— 决策到 RuntimeToolCall / RuntimeAgentCall 的映射

所以它能抓到：能力没登记进路由白名单（就是 `generate_report` 那一类 bug）、参数 schema 漂移、
归属校验误杀自有资源、能力改名后注册表不同步。这些恰恰是迁移期最容易出的错。

它**不测**模型判断力——那是 test_planner_accuracy.py 的职责，需要真实调用。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.agent.capability_registry import get_capability
from tests.ai.eval.cases import GOLDEN_CASES, PlannerEvalCase
from tests.ai.eval.harness import default_eval_config, run_cases

UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def canonical_planner_payload(case: PlannerEvalCase) -> dict[str, Any]:
    """构造「模型本应给出的规范输出」。

    只依赖用例自身的期望值（expected_action / expected_capability /
    expected_arguments_subset）与能力的 JSON Schema required 字段，
    不依赖任何录制，因此加能力、改 prompt 都不会让它过期。
    """
    if case.expected_action == "none":
        return {"action": "none", "capability": None, "arguments": {}, "reason": "canonical_none"}

    capability = get_capability(case.expected_capability or "")
    assert capability is not None, (
        f"用例 {case.case_id} 期望调用 {case.expected_capability}，"
        "但它不在能力注册表里——能力改名或注册漏了。"
    )

    required = capability.argument_model.model_json_schema().get("required", [])
    arguments: dict[str, Any] = {"reason": "canonical"}

    if "imagery_id" in required:
        assert case.imagery_inventory, (
            f"用例 {case.case_id} 要调用需要 imagery_id 的能力，但没有配影像 fixture。"
        )
        arguments["imagery_id"] = case.imagery_inventory[0].imagery_id
    if "document_id" in required:
        found = UUID_PATTERN.search(case.query)
        assert found, f"用例 {case.case_id} 要调 parse_document，但 query 里没有 document UUID。"
        arguments["document_id"] = found.group(0)
    if "query" in required:
        arguments["query"] = case.query
    if case.min_query_count > 1:
        # 复合检索：规划器要给每个意图各一条聚焦检索词
        arguments["queries"] = [f"{case.query} #{i + 1}" for i in range(case.min_query_count)]

    # 用例显式声明的参数期望优先级最高（如 index_type=nbr、mode=true_color）
    arguments.update(case.expected_arguments_subset)

    return {
        "action": "call",
        "capability": capability.name,
        "arguments": arguments,
        "reason": "canonical_call",
    }


class CanonicalPlannerClient:
    """确定性假模型：永远返回该用例的规范规划输出。"""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._text = json.dumps(payload, ensure_ascii=False)
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **_kwargs: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._text))]
        )


# 评测 harness 强制 DATABASE_ENABLED=false（harness.py:132），而文档工具的归属校验
# 在没有连接池时直接返回 document_not_found_or_forbidden（tool_guards.py），
# 所以文档类用例在本框架里**结构性地永远过不了**，与管线是否健康无关。
#
# 这不是本文件引入的问题：现有 replay 评测的阈值是 MIN_REPLAY_ACCURACY=0.85，
# 1/31 的失败被容忍掉了，所以一直没人注意。这里不静默跳过，而是把它显式断言成
# 「已知环境限制」——真正修复需要给 harness 接一个带文档 fixture 的库，属独立工作。
DB_DEPENDENT_CASE_IDS = frozenset({"tool_parse_document"})
DB_DEPENDENT_EXPECTED_ERROR = "document_not_found_or_forbidden"


async def _run_canonical(cases, tmp_path: Path):
    payloads = {case.case_id: canonical_planner_payload(case) for case in cases}
    return await run_cases(
        cases,
        tmp_root=tmp_path,
        client_factory=lambda context: CanonicalPlannerClient(payloads[context.case_id]),
        config=default_eval_config("canonical-pipeline"),
    )


@pytest.mark.asyncio
async def test_pipeline_turns_canonical_output_into_expected_decision(tmp_path: Path) -> None:
    """规范输出进去，期望决策出来——除已知依赖库的用例外，每条都必须成立。"""
    cases = tuple(case for case in GOLDEN_CASES if case.case_id not in DB_DEPENDENT_CASE_IDS)
    assert cases, "全部用例都被排除了，说明排除名单写错了"

    results = await _run_canonical(cases, tmp_path)

    failures = [
        f"{r.case_id}: 期望 {r.expected_label} → 实得 {r.actual_label}"
        + (f"（校验拒绝: {r.validation_error}）" if r.validation_error else "")
        + (f"（原因: {r.mismatch_reason}）" if r.mismatch_reason else "")
        for r in results
        if not r.correct
    ]
    assert not failures, (
        "决策管线没能把规范规划输出转成期望决策。这不是模型判断力问题，"
        "是路由白名单／参数 schema／归属鉴权／能力注册表中的某一处坏了：\n  "
        + "\n  ".join(failures)
    )


@pytest.mark.asyncio
async def test_db_dependent_cases_fail_only_for_the_known_reason(tmp_path: Path) -> None:
    """文档类用例必须**只**因「无库」这一个已知原因被拒，不能是别的毛病。

    把已知限制钉成断言而不是跳过：一旦拒绝原因变了（比如参数 schema 漂移导致
    invalid_arguments），这里立刻失败；一旦将来给 harness 接了库让它能通过，
    这里也会失败，提醒把该用例移回上面的严格断言。
    """
    cases = tuple(case for case in GOLDEN_CASES if case.case_id in DB_DEPENDENT_CASE_IDS)
    assert len(cases) == len(DB_DEPENDENT_CASE_IDS), "排除名单里有不存在的 case_id"

    results = await _run_canonical(cases, tmp_path)

    for result in results:
        assert result.validation_error == DB_DEPENDENT_EXPECTED_ERROR, (
            f"{result.case_id} 的失败原因变了：期望 {DB_DEPENDENT_EXPECTED_ERROR}，"
            f"实得 {result.validation_error!r}。"
            "若是因为 harness 接上了库使它现在能通过，请把它移出 DB_DEPENDENT_CASE_IDS。"
        )


@pytest.mark.asyncio
async def test_ownership_guard_blocks_other_users_imagery(tmp_path: Path) -> None:
    """归属 guard 必须拦下别人的影像——**不依赖模型先犯错**。

    这条断言原先挂在 replay 测试里（test_planner_accuracy.py），写法是「跑一遍模型，
    然后断言 validation_error == imagery_not_found_or_forbidden」。问题是它把
    「鉴权兜底是否有效」寄托在「模型必须先尝试越权」上：

    - qwen3.7-max 会去调那个不属于自己的 imagery_id，guard 拦住 → 断言成立；
    - deepseek-v4-pro 更谨慎，planner 阶段自己就拒了（它只看得到当前用户的影像清单），
      guard 根本没被触发 → validation_error 是 None，断言失败，**而 guard 其实没坏**。

    模型越谨慎，这层兜底就越测不到——这是反的。所以这里改成直接构造越权调用，
    强制走到 guard，无论上游模型怎么表现都必然覆盖。
    """
    case = next(c for c in GOLDEN_CASES if c.case_id == "edge_non_owner_imagery")
    assert case.imagery_inventory, "用例应带一个属于他人的影像 fixture"
    foreign = case.imagery_inventory[0]
    assert foreign.owner_user_id != case.user_id, "fixture 必须属于另一个用户，否则测不到越权"

    # 故意构造一次越权调用：模型「说」要算这张别人的影像的 NDVI
    adversarial = {
        "action": "call",
        "capability": "calculate_ndvi",
        "arguments": {"imagery_id": foreign.imagery_id, "reason": "adversarial_cross_user_access"},
        "reason": "adversarial",
    }

    results = await run_cases(
        (case,),
        tmp_root=tmp_path,
        client_factory=lambda _context: CanonicalPlannerClient(adversarial),
        config=default_eval_config("canonical-pipeline"),
    )
    result = results[0]

    assert result.validation_error == "imagery_not_found_or_forbidden", (
        "越权调用没有被归属 guard 拦下——鉴权出现漏洞。"
        f"实际 validation_error={result.validation_error!r}"
    )
    assert result.actual_action == "none", (
        f"被 guard 拒绝后最终决策必须是 none，实得 {result.actual_action!r}"
    )


@pytest.mark.asyncio
async def test_every_registered_capability_is_reachable(tmp_path: Path) -> None:
    """每个已注册能力都必须至少被一条 golden 用例覆盖到，且真能被路由放行。

    仓库当前 2 个失败测试的成因就是「加了 generate_report 但配套没跟上」。
    这条断言让「新增能力却没进评测集」立刻暴露，而不是等录制过期才发现。
    """
    from app.agent.capability_registry import list_capabilities

    registered = {cap.name for cap in list_capabilities(available_only=False)}
    covered = {case.expected_capability for case in GOLDEN_CASES if case.expected_capability}

    missing = sorted(registered - covered)
    assert not missing, (
        "以下能力已注册但没有任何 golden 用例覆盖，新增能力时请补用例：\n  "
        + "\n  ".join(missing)
    )

    unknown = sorted(covered - registered)
    assert not unknown, (
        "以下用例期望的能力不在注册表里（能力被改名或删除？）：\n  " + "\n  ".join(unknown)
    )

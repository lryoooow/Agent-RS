"""heldout 防作弊与纪律测试。

这组测试是 heldout 可信度的根基：任何"为通过而通过"的旁路（贴 prompt 造题、
复用 dev-set 常量、改题重冻结、sealed 后重采、封存后篡改录制）都必须在这里变红。
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from tests.ai.eval.cases import (
    DEFAULT_USER_ID,
    DOCUMENT_ID,
    ImageryFixture,
    OTHER_IMAGERY_ID,
    PRIMARY_IMAGERY_ID,
)
from tests.ai.eval.cases_generator import FEW_SHOT_QUERIES
from tests.ai.eval.heldout_generator import (
    HELDOUT_DATASET,
    HELDOUT_V1_SEED,
    dataset_hash,
    generate_heldout_cases,
    heldout_summary,
    validate_heldout_cases,
)
from tests.ai.eval.heldout_intents import IntentSpec, derive_label
from tests.ai.eval.heldout_manifest import (
    HeldoutDisciplineError,
    SealedRunError,
    abort_run,
    assert_dataset_frozen,
    assert_run_sealed,
    freeze_dataset,
    prepare_live_run,
    seal_run,
)


EVAL_DIR = Path(__file__).resolve().parent
_HELDOUT_MODULES = ("heldout_generator.py", "heldout_intents.py", "heldout_phrasing.py")


@pytest.fixture(scope="module")
def heldout_cases():
    return generate_heldout_cases()


# ---------------------------------------------------------------------------
# 防作弊：题库来源纯净


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


@pytest.mark.parametrize("module_name", _HELDOUT_MODULES)
def test_generator_does_not_import_planner_prompt(module_name: str) -> None:
    names = _imported_names(EVAL_DIR / module_name)
    assert "_planner_prompt" not in names, f"{module_name} 反向贴 prompt 被拦截"
    assert not any(name.startswith("app.agent.llm_planner") for name in names), (
        f"{module_name} 不得 import llm_planner 模块"
    )


def test_heldout_queries_not_verbatim_fewshot(heldout_cases) -> None:
    few_shot = set(FEW_SHOT_QUERIES)
    leaked = [case.case_id for case in heldout_cases if case.query in few_shot]
    assert not leaked, f"heldout 与 few-shot 整句重复: {leaked[:5]}"


def test_heldout_ids_not_devset_constants(heldout_cases) -> None:
    forbidden = (PRIMARY_IMAGERY_ID, OTHER_IMAGERY_ID, DOCUMENT_ID)
    offenders = [
        case.case_id
        for case in heldout_cases
        if any(bad in case.query for bad in forbidden)
        or any(item.imagery_id in forbidden for item in case.imagery_inventory)
    ]
    assert not offenders, f"heldout 复用 dev-set ID 常量: {offenders[:5]}"


def test_heldout_queries_globally_unique(heldout_cases) -> None:
    queries = [case.query for case in heldout_cases]
    assert len(queries) == len(set(queries)), "存在整句重复（题量虚胖）"


# ---------------------------------------------------------------------------
# 防作弊：确定性与标注可重算


def test_dataset_hash_stable_under_seed(heldout_cases) -> None:
    again = generate_heldout_cases()
    assert dataset_hash(heldout_cases) == dataset_hash(again)
    other_seed = generate_heldout_cases(seed=HELDOUT_V1_SEED + 1)
    assert dataset_hash(heldout_cases) != dataset_hash(other_seed)


def test_heldout_labels_rule_derived(heldout_cases) -> None:
    """每条 label 必须能由意图状态重算：从 case 反推状态量，经 derive_label 得到一致结论。"""

    for case in heldout_cases:
        owned = [item for item in case.imagery_inventory if item.owner_user_id == case.user_id]
        query_has_owned_id = any(item.imagery_id in case.query for item in owned)
        if case.scoring == "diagnostic_unsupported":
            intent = IntentSpec("compound", "unsupported_multi_tool", None)
            label = derive_label(intent, imagery_id=None, document_id=None, inventory=case.imagery_inventory)
        elif case.expected_action == "call":
            cap = case.expected_capability
            if cap == "web_search":
                subtype = "web_search_multi" if case.min_query_count else "pos"
                intent = IntentSpec("positive", subtype, "web_search")
                label = derive_label(intent, imagery_id=None, document_id=None, inventory=case.imagery_inventory)
            elif cap == "parse_document":
                doc = case.expected_arguments_subset.get("document_id")
                assert doc and str(doc) in case.query, f"{case.case_id}: 文档 call 必须在 query 写明 doc id"
                intent = IntentSpec("positive", "pos", cap, document_state="valid")
                label = derive_label(intent, imagery_id=None, document_id=str(doc), inventory=case.imagery_inventory)
            else:
                img = str(case.expected_arguments_subset.get("imagery_id"))
                extra = {
                    k: v
                    for k, v in case.expected_arguments_subset.items()
                    if k not in {"imagery_id"}
                }
                # badid/corrupted_id 多图唯一匹配的 call：忠实重算需 query 里的损坏 ID（provided_imagery_ref），
                # case 字段反推不到。其 action 分流由纯函数 test_corrupted_id_multi_image_* 覆盖、
                # capability↔task 由 test_*_capability_matches_query_task 覆盖，此处跳过避免假重算。
                owned_n = sum(1 for it in case.imagery_inventory if it.owner_user_id == case.user_id)
                if ("badid" in case.case_id or "corrupted_id" in case.category) and owned_n > 1:
                    continue
                if query_has_owned_id:
                    state = "valid"
                elif "badid" in case.case_id or "corrupted_id" in case.category:
                    state = "invalid"
                else:
                    state = "unreferenced"
                intent = IntentSpec("positive", "pos", cap, imagery_state=state, arguments=extra)
                label = derive_label(
                    intent,
                    imagery_id=img,
                    document_id=None,
                    inventory=case.imagery_inventory,
                )
        else:
            # none 用例：必须不存在"query 写明了自有可用影像 ID 且意图可执行"的旁证。
            assert not case.expected_arguments_subset, f"{case.case_id}: none 不应带参数期望"
            if query_has_owned_id:
                # 清单真图 ID 出现在 query 里却标 none，只允许概念/否定/矛盾类（allow_tool/无意图）。
                category = case.category
                assert any(
                    tag in category
                    for tag in ("concept", "negation", "contradiction")
                ), f"{case.case_id}: query 含自有 ID 却标 none，类别 {category} 不在豁免集"
                intent = IntentSpec("hard_negative", "recheck", None, imagery_state="valid")
                label = derive_label(
                    intent,
                    imagery_id=next(iter(owned)).imagery_id if owned else None,
                    document_id=None,
                    inventory=case.imagery_inventory,
                )
            elif "non_owner" in case.category:
                img = case.imagery_inventory[0].imagery_id if case.imagery_inventory else None
                intent = IntentSpec("hard_negative", "non_owner", "calculate_ndvi", imagery_state="non_owner")
                label = derive_label(intent, imagery_id=img, document_id=None, inventory=case.imagery_inventory)
            elif "missing_id_pronoun" in case.category:
                img = case.imagery_inventory[0].imagery_id if case.imagery_inventory else None
                # capability 据 query task 同源（已由 test_*_capability_matches_query_task 独立验证），
                # 这里用 case 自带 capability 重建 intent，专验多图/单图的 action+补全逻辑。
                intent = IntentSpec(
                    "hard_negative",
                    "missing_id_pronoun",
                    case.expected_capability or "calculate_ndvi",
                    imagery_state="unreferenced",
                    arguments={k: v for k, v in case.expected_arguments_subset.items() if k != "imagery_id"},
                )
                label = derive_label(intent, imagery_id=img, document_id=None, inventory=case.imagery_inventory)
            else:
                intent = IntentSpec("hard_negative", "recheck", None)
                label = derive_label(intent, imagery_id=None, document_id=None, inventory=case.imagery_inventory)
        assert label.expected_action == case.expected_action, case.case_id
        assert label.expected_capability == case.expected_capability, case.case_id
        if case.expected_action == "call" and case.expected_capability not in {"web_search"}:
            assert label.expected_arguments_subset == case.expected_arguments_subset, case.case_id


def test_heldout_layer_validation_passes(heldout_cases) -> None:
    validate_heldout_cases(heldout_cases)
    summary = heldout_summary(heldout_cases)
    assert summary["total"] == 1000
    assert summary["unique_queries"] == 1000
    assert summary["kinds"] == {
        "positive": 350,
        "hard_negative": 300,
        "boundary": 200,
        "compound": 100,
        "noise": 50,
    }


def test_heldout_validation_rejects_devset_id_reuse(heldout_cases) -> None:
    from dataclasses import replace

    poisoned = (replace(heldout_cases[0], query=f"计算影像 {PRIMARY_IMAGERY_ID} 的 NDVI"),) + tuple(
        heldout_cases[1:]
    )
    with pytest.raises(ValueError, match="dev-set ID"):
        validate_heldout_cases(poisoned)


def test_heldout_validation_rejects_duplicate_query(heldout_cases) -> None:
    from dataclasses import replace

    poisoned = (replace(heldout_cases[0], query=heldout_cases[1].query, case_id="dup_query"),) + tuple(
        heldout_cases[1:]
    )
    with pytest.raises(ValueError, match="duplicate query"):
        validate_heldout_cases(poisoned)


# ---------------------------------------------------------------------------
# 噪声分叉：ID 损坏必须 none 且查询里不能出现完整真 ID


def test_noise_badid_unique_image_is_call_with_real_inventory(heldout_cases) -> None:
    """按修正口径精确断言（非放松）：badid 三类边界——

    - 单图 / 多图但损坏ID唯一前缀匹配 → call，补全清单里某张真图完整 ID
    - 多图且损坏ID匹配多张（诱饵共享前缀）→ none（真歧义）
    其中 call 类的真 ID 不得出现在 query（query 写的是损坏 ID）。
    """
    badid = [case for case in heldout_cases if case.case_id.startswith("heldout_noise_badid_")]
    assert badid, "缺少 ID 损坏噪声用例"
    call_cnt = none_cnt = 0
    for case in badid:
        assert case.imagery_inventory, f"{case.case_id}: 必须有真图清单（诱导陷阱）"
        owned_ids = {item.imagery_id for item in case.imagery_inventory if item.owner_user_id == DEFAULT_USER_ID}
        if case.expected_action == "call":
            picked = case.expected_arguments_subset["imagery_id"]
            assert picked in owned_ids, f"{case.case_id}: 补全的 ID 必须在自有清单内"
            assert picked not in case.query, f"{case.case_id}: 完整真 ID 不得出现在 query"
            call_cnt += 1
        else:
            assert case.expected_action == "none", case.case_id
            assert not case.expected_capability, f"{case.case_id}: none 不带 capability"
            none_cnt += 1
    assert call_cnt > 0 and none_cnt > 0, f"badid 应同时覆盖 call/none 边界，实际 call={call_cnt} none={none_cnt}"



def test_noise_badid_multi_image_is_none() -> None:
    inventory = (
        ImageryFixture("123456abcdef"),
        ImageryFixture("123456999999"),
    )
    intent = IntentSpec("noise", "corrupted_id", "calculate_ndvi", imagery_state="invalid")
    label = derive_label(intent, imagery_id="123456abcdef", document_id=None, inventory=inventory)
    assert label.expected_action == "none"
    assert label.expected_capability is None


def test_heldout_missing_id_corrupted_capability_matches_query_task(heldout_cases) -> None:
    """回归（历史重复问题点，与 stress 同源 bug）：missing_id_pronoun / corrupted_id
    的 expected_capability 必须与 query 写的 task 同源，不许写死 calculate_ndvi。

    heldout_generator 与 stress_generator 共用 heldout_phrasing 的 realize 函数，曾同样
    写死 capability。heldout-v2 (#17) 据此生成，复发会直接污染盲测，故设硬回归守卫。
    """

    task2cap = {"NDVI": "calculate_ndvi", "水体掩膜": "extract_water_mask",
                "地物分割": "segment_landcover", "云检测": "cloud_shadow_mask"}
    checked = 0
    for case in heldout_cases:
        cid = case.case_id
        if not ("missing_id" in cid or "noise_badid" in cid):
            continue
        if case.expected_action != "call":
            continue  # 空清单/多图→none，不判 capability
        tasks = [t for t in task2cap if t in case.query]
        assert tasks, f"{cid}: query 未含已知 task: {case.query!r}"
        assert case.expected_capability == task2cap[tasks[0]], (
            f"{cid}: query task={tasks[0]} 应映射 {task2cap[tasks[0]]}，"
            f"实际 {case.expected_capability}（写死 bug 复发）"
        )
        checked += 1
    assert checked > 0, "未覆盖任何 call 类 missing_id/badid，样本不足"



def test_noise_dirty_cases_keep_call_label(heldout_cases) -> None:
    dirty = [case for case in heldout_cases if case.case_id.startswith("heldout_noise_dirty_")]
    assert dirty, "缺少脏文本噪声用例"
    for case in dirty:
        assert case.expected_action == "call", case.case_id
        img = str(case.expected_arguments_subset.get("imagery_id"))
        assert img and img in case.query, f"{case.case_id}: 脏文本不得破坏 ID"


def test_compound_web_search_requires_multi_query(heldout_cases) -> None:
    web = [case for case in heldout_cases if case.case_id.startswith("heldout_cmp_web_")]
    assert len(web) >= 30, "复合 web_search 数量不足"
    for case in web:
        assert case.expected_capability == "web_search"
        assert case.min_query_count == 2, case.case_id
        assert case.scoring == "main"


# ---------------------------------------------------------------------------
# 冻结与 run 状态机纪律


def _mini_cases():
    return generate_heldout_cases(seed=4242, target=100, dataset="heldout-mini")


def test_freeze_is_idempotent_but_rejects_changed_dataset(tmp_path: Path) -> None:
    cases = _mini_cases()
    out = tmp_path / "frozen"
    first = freeze_dataset(cases, dataset_id="heldout-mini", seed=4242, out_dir=out, label_policy="rule-derived")
    second = freeze_dataset(cases, dataset_id="heldout-mini", seed=4242, out_dir=out, label_policy="rule-derived")
    assert first == second
    changed = generate_heldout_cases(seed=4243, target=100, dataset="heldout-mini")
    with pytest.raises(HeldoutDisciplineError, match="re-freeze"):
        freeze_dataset(changed, dataset_id="heldout-mini", seed=4243, out_dir=out, label_policy="rule-derived")


def test_assert_dataset_frozen_blocks_tampered_cases(tmp_path: Path) -> None:
    from dataclasses import replace

    cases = _mini_cases()
    out = tmp_path / "frozen"
    freeze_dataset(cases, dataset_id="heldout-mini", seed=4242, out_dir=out, label_policy="rule-derived")
    assert_dataset_frozen(cases, out)
    tampered = (replace(cases[0], query=cases[0].query + "（事后改题）"),) + tuple(cases[1:])
    with pytest.raises(HeldoutDisciplineError, match="hash mismatch"):
        assert_dataset_frozen(tampered, out)


def _write_fake_recording(run_dir: Path, case_id: str) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / f"{case_id}.json").write_text(
        json.dumps({"case_id": case_id, "raw_texts": ["{}"]}), encoding="utf-8"
    )


def test_sealed_run_rejects_relive(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    pins = dict(dataset_id="heldout-mini", dataset_hash="h" * 64, prompt_hash="p" * 64, model="m")
    manifest = prepare_live_run(run_dir, **pins)
    assert manifest["status"] == "in_progress"
    # 断点续录：in_progress + pin 一致 → 允许。
    resumed = prepare_live_run(run_dir, **pins)
    assert resumed["run_id"] == manifest["run_id"]
    # pin 不一致 → 拒绝。
    with pytest.raises(HeldoutDisciplineError, match="pins mismatch"):
        prepare_live_run(run_dir, **{**pins, "prompt_hash": "x" * 64})
    _write_fake_recording(run_dir, "case_a")
    sealed = seal_run(run_dir, expected_case_ids=["case_a"])
    assert sealed["status"] == "sealed"
    # sealed 后重采 → 必须红。
    with pytest.raises(SealedRunError):
        prepare_live_run(run_dir, **pins)


def test_seal_requires_complete_recordings(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    prepare_live_run(
        run_dir, dataset_id="d", dataset_hash="h" * 64, prompt_hash="p" * 64, model="m"
    )
    _write_fake_recording(run_dir, "case_a")
    with pytest.raises(HeldoutDisciplineError, match="missing"):
        seal_run(run_dir, expected_case_ids=["case_a", "case_b"])


def test_sealed_recordings_tamper_detected(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    prepare_live_run(
        run_dir, dataset_id="d", dataset_hash="h" * 64, prompt_hash="p" * 64, model="m"
    )
    _write_fake_recording(run_dir, "case_a")
    seal_run(run_dir, expected_case_ids=["case_a"])
    assert_run_sealed(run_dir)
    # 封存后篡改录制 → digest 不一致必须红。
    (run_dir / "case_a.json").write_text(
        json.dumps({"case_id": "case_a", "raw_texts": ['{"action":"call"}']}), encoding="utf-8"
    )
    with pytest.raises(HeldoutDisciplineError, match="tamper"):
        assert_run_sealed(run_dir)


def test_aborted_run_cannot_resume_or_score(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    pins = dict(dataset_id="d", dataset_hash="h" * 64, prompt_hash="p" * 64, model="m")
    prepare_live_run(run_dir, **pins)
    abort_run(run_dir, reason="api outage")
    with pytest.raises(HeldoutDisciplineError, match="aborted"):
        prepare_live_run(run_dir, **pins)
    with pytest.raises(HeldoutDisciplineError, match="sealed run"):
        assert_run_sealed(run_dir)


def test_official_score_requires_sealed_status(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    prepare_live_run(
        run_dir, dataset_id="d", dataset_hash="h" * 64, prompt_hash="p" * 64, model="m"
    )
    _write_fake_recording(run_dir, "case_a")
    with pytest.raises(HeldoutDisciplineError, match="sealed"):
        assert_run_sealed(run_dir)


# ---------------------------------------------------------------------------
# prompt_near 与默认数据集冻结锚


def test_prompt_near_cases_marked_and_will_be_excluded(heldout_cases) -> None:
    """prompt_near 标记存在即剔出 hard score（复用 compute_grouped_metrics 的既有逻辑）。"""

    summary = heldout_summary(heldout_cases)
    # 表达层刻意避开 few-shot；若未来改句式贴近了 few-shot，这里给出可见信号。
    assert summary["prompt_near"] <= 20, "prompt_near 占比异常升高，疑似句式贴 few-shot"


def test_default_dataset_identity_is_pinned() -> None:
    """锚定默认 seed/target/dataset 名：变更必须显式过审，防悄改。"""

    cases = generate_heldout_cases()
    assert HELDOUT_V1_SEED == 20260610
    assert HELDOUT_DATASET == "heldout-v1"
    assert len(cases) == 1000

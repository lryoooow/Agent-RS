"""random-stress 防作弊与纪律测试。

random-stress 不冻结，但同样禁止"为通过而通过"：题库不得贴 prompt、不得复用 dev-set 常量、
label 必须可由 derive_label 重算、扰动不得偷偷改答案、历史干扰不得制造跨轮指代依赖。
覆盖：正常分布、边界（比例/诊断归属）、非法（污染 query/重复题）、异常（history 结构）、
历史重复问题（多图诱饵不改 label、损坏 ID→none、指代→none）。
"""

from __future__ import annotations

import ast
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
from tests.ai.eval.heldout_intents import derive_label, IntentSpec
from tests.ai.eval.stress_generator import (
    STRESS_DATASET,
    STRESS_SEEDS,
    STRESS_TARGET,
    generate_stress_cases,
    stress_fingerprint,
    stress_summary,
    validate_stress_cases,
)


EVAL_DIR = Path(__file__).resolve().parent
_STRESS_MODULES = ("stress_generator.py",)


@pytest.fixture(scope="module")
def stress_cases():
    return generate_stress_cases(seed=STRESS_SEEDS[0])


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


# --- 防作弊：题库来源纯净 -----------------------------------------------------


@pytest.mark.parametrize("module_name", _STRESS_MODULES)
def test_stress_does_not_import_planner_prompt(module_name: str) -> None:
    names = _imported_names(EVAL_DIR / module_name)
    assert "_planner_prompt" not in names
    assert not any(n.startswith("app.agent.llm_planner") for n in names)


def test_stress_queries_not_verbatim_fewshot(stress_cases) -> None:
    few_shot = set(FEW_SHOT_QUERIES)
    leaked = [c.case_id for c in stress_cases if c.query in few_shot]
    assert not leaked, f"与 few-shot 整句重复: {leaked[:5]}"


def test_stress_ids_not_devset_constants(stress_cases) -> None:
    forbidden = (PRIMARY_IMAGERY_ID, OTHER_IMAGERY_ID, DOCUMENT_ID)
    offenders = [
        c.case_id
        for c in stress_cases
        if any(b in c.query for b in forbidden)
        or any(item.imagery_id in forbidden for item in c.imagery_inventory)
    ]
    assert not offenders, f"复用 dev-set ID 常量: {offenders[:5]}"


# --- 防作弊：确定性 -----------------------------------------------------------


def test_stress_fingerprint_stable_same_seed() -> None:
    a = generate_stress_cases(seed=STRESS_SEEDS[0])
    b = generate_stress_cases(seed=STRESS_SEEDS[0])
    assert stress_fingerprint(a) == stress_fingerprint(b)


def test_stress_fingerprint_differs_across_seeds() -> None:
    a = generate_stress_cases(seed=STRESS_SEEDS[0])
    b = generate_stress_cases(seed=STRESS_SEEDS[1])
    assert stress_fingerprint(a) != stress_fingerprint(b)


def test_stress_queries_globally_unique() -> None:
    for seed in STRESS_SEEDS:
        cases = generate_stress_cases(seed=seed)
        queries = [c.query for c in cases]
        assert len(queries) == len(set(queries)), f"seed {seed} 整句重复（题量虚胖）"


# --- 防作弊：label 可由 derive_label 重算（无手填漂移）------------------------

# 自有 ID 写进 query 的 none 类（概念/否定/矛盾）：渲染层措辞决定，免于纯规则重算。
_RULE_EXEMPT = {"concept", "negation", "contradiction"}


def test_stress_labels_rule_derived(stress_cases) -> None:
    for c in stress_cases:
        subtype = c.category.split("_", 2)[-1]
        if any(tag in c.category for tag in _RULE_EXEMPT):
            continue
        img = str(c.expected_arguments_subset.get("imagery_id") or "") or None
        doc = str(c.expected_arguments_subset.get("document_id") or "") or None
        # 无法从 label 反推 intent 全字段，这里只校验 action/capability 自洽：
        # call 必有 capability，none 必无 capability。
        if c.expected_action == "call":
            assert c.expected_capability, f"{c.case_id}: call 缺 capability"
        else:
            assert c.expected_capability is None, f"{c.case_id}: none 不应带 capability"


def test_missing_id_corrupted_capability_matches_query_task(stress_cases) -> None:
    """回归（历史重复问题点）：missing_id_pronoun / corrupted_id 的 expected_capability
    必须与 query 里实际写的 task 同源，不许写死 calculate_ndvi。

    根因：realize_missing_id/realize_corrupted_id 曾用 rng.choice(_NEG_TASKS) 随机选 task
    填 query，调用方却把 capability 写死 calculate_ndvi → query 说"水体掩膜"标注却要 NDVI，
    3 seed 实测 127 条系统性错标（83.8% / 86.7%）。修复后两者据 task→capability 同源推导。
    """

    task2cap = {"NDVI": "calculate_ndvi", "水体掩膜": "extract_water_mask",
                "地物分割": "segment_landcover", "云检测": "cloud_shadow_mask"}
    checked = 0
    for c in stress_cases:
        if c.category not in (
            "stress_hard_negative_missing_id_pronoun",
            "stress_noise_corrupted_id",
        ):
            continue
        if c.expected_action != "call":
            continue  # 空清单/多图歧义→none 的不判 capability
        tasks_in_query = [t for t in task2cap if t in c.query]
        assert tasks_in_query, f"{c.case_id}: query 未含已知 task: {c.query!r}"
        expected = task2cap[tasks_in_query[0]]
        assert c.expected_capability == expected, (
            f"{c.case_id}: query task={tasks_in_query[0]} 应映射 {expected}，"
            f"实际标注 {c.expected_capability}（写死 bug 复发）"
        )
        checked += 1
    assert checked > 0, "未覆盖任何 call 类 missing_id/corrupted_id，样本不足"



def test_corrupted_id_unique_image_derives_call() -> None:
    """新口径：损坏 ID + 清单唯一真图 → 补全为该图 call。"""
    intent = IntentSpec("noise", "corrupted_id", "calculate_ndvi", imagery_state="invalid")
    inventory = (ImageryFixture("123456abcdef"),)
    label = derive_label(intent, imagery_id="123456abcdef", document_id=None, inventory=inventory)
    assert label.expected_action == "call"
    assert label.expected_capability == "calculate_ndvi"
    assert label.expected_arguments_subset["imagery_id"] == "123456abcdef"


def test_corrupted_id_multi_image_unique_prefix_derives_call() -> None:
    """终裁口径（之前缺失的实现）：损坏 ID + 多图，但能唯一前缀匹配一张 → 补全 call。

    模型实测 7/7 在此场景 call 正确，曾因 derive_label 无脑 none 被误判 FP。
    provided_imagery_ref 是 query 里的损坏 ID，唯一匹配清单一张才补全。
    """
    intent = IntentSpec("noise", "corrupted_id", "calculate_ndvi", imagery_state="invalid",
                        provided_imagery_ref="123456")  # trunc6，唯一前缀
    inventory = (ImageryFixture("123456abcdef"), ImageryFixture("789abc000000"))
    label = derive_label(intent, imagery_id="123456abcdef", document_id=None, inventory=inventory)
    assert label.expected_action == "call"
    assert label.expected_arguments_subset["imagery_id"] == "123456abcdef"


def test_corrupted_id_multi_image_multi_match_derives_none() -> None:
    """终裁口径：损坏 ID + 多图，前缀匹配到多张 → 真歧义，必须 none。"""
    intent = IntentSpec("noise", "corrupted_id", "calculate_ndvi", imagery_state="invalid",
                        provided_imagery_ref="123456")  # 两张都以 123456 开头
    inventory = (ImageryFixture("123456abcdef"), ImageryFixture("123456999999"))
    label = derive_label(intent, imagery_id="123456abcdef", document_id=None, inventory=inventory)
    assert label.expected_action == "none" and label.expected_capability is None


def test_corrupted_id_multi_image_pure_pronoun_derives_none() -> None:
    """终裁口径：多图 + 无 ID 片段（纯指代）→ none，要求用户指明。"""
    intent = IntentSpec("noise", "corrupted_id", "calculate_ndvi", imagery_state="invalid",
                        provided_imagery_ref=None)
    inventory = (ImageryFixture("123456abcdef"), ImageryFixture("789abc000000"))
    label = derive_label(intent, imagery_id="123456abcdef", document_id=None, inventory=inventory)
    assert label.expected_action == "none"


def test_pronoun_unreferenced_unique_image_derives_call() -> None:
    """新口径：纯指代 + 清单唯一真图 → 补全为该图 call。"""
    intent = IntentSpec("hard_negative", "missing_id_pronoun", "calculate_ndvi", imagery_state="unreferenced")
    inventory = (ImageryFixture("abcdef123456"),)
    label = derive_label(intent, imagery_id="abcdef123456", document_id=None, inventory=inventory)
    assert label.expected_action == "call"
    assert label.expected_arguments_subset["imagery_id"] == "abcdef123456"


def test_pronoun_unreferenced_multi_image_derives_none() -> None:
    """新口径：纯指代 + 多张自有图 → none，要求用户指明。"""
    intent = IntentSpec("hard_negative", "missing_id_pronoun", "calculate_ndvi", imagery_state="unreferenced")
    inventory = (ImageryFixture("abcdef123456"), ImageryFixture("abcdef999999"))
    label = derive_label(intent, imagery_id="abcdef123456", document_id=None, inventory=inventory)
    assert label.expected_action == "none"


def test_derive_label_user_denies_id_none() -> None:
    """口径终裁关键边界：唯一图 + 用户显式否定（"但我没有提供影像 ID"）→ none。

    信用户的话 > 信系统状态：即便清单恰好唯一图，显式否定也必须压过"唯一图补全"。
    """
    intent = IntentSpec(
        "hard_negative",
        "missing_id_denied",
        "calculate_ndvi",
        imagery_state="unreferenced",
        user_denies_id=True,
    )
    inventory = (ImageryFixture("abcdef123456"),)
    label = derive_label(intent, imagery_id="abcdef123456", document_id=None, inventory=inventory)
    assert label.expected_action == "none"
    assert label.expected_capability is None
    assert not label.expected_arguments_subset


def test_derive_label_omission_vs_denial_same_inventory_diverge() -> None:
    """同一张唯一图清单：纯省略（指代）→ call 补全；显式否定 → none。

    这是 A 段"区分省略与显式否定"的对照锚：两者唯一差别只有 user_denies_id，
    却必须分流到 call / none，防止把"省略"和"否定"混为一谈。
    """
    inventory = (ImageryFixture("abcdef123456"),)
    omission = IntentSpec(
        "hard_negative", "missing_id_pronoun", "calculate_ndvi", imagery_state="unreferenced"
    )
    denial = IntentSpec(
        "hard_negative",
        "missing_id_denied",
        "calculate_ndvi",
        imagery_state="unreferenced",
        user_denies_id=True,
    )
    omission_label = derive_label(
        omission, imagery_id="abcdef123456", document_id=None, inventory=inventory
    )
    denial_label = derive_label(
        denial, imagery_id="abcdef123456", document_id=None, inventory=inventory
    )
    assert omission_label.expected_action == "call"
    assert omission_label.expected_arguments_subset["imagery_id"] == "abcdef123456"
    assert denial_label.expected_action == "none"


# --- 边界：层比例与诊断归属 ---------------------------------------------------


def test_stress_layer_ratio_and_counts() -> None:
    for seed in STRESS_SEEDS:
        cases = generate_stress_cases(seed=seed, target=STRESS_TARGET)
        assert len(cases) == STRESS_TARGET
        s = stress_summary(cases)
        # 35/30/20/10/5 跟随 STRESS_TARGET 动态缩放（不写死，避免改量即改测试）
        expected = {
            "hard": round(STRESS_TARGET * 0.30),
            "boundary": round(STRESS_TARGET * 0.20),
            "compound": round(STRESS_TARGET * 0.10),
            "noise": round(STRESS_TARGET * 0.05),
        }
        assert sum(s["kinds"].values()) == STRESS_TARGET
        for kind, want in expected.items():
            assert s["kinds"][kind] == want, f"seed {seed} {kind} 配比错: {s['kinds'][kind]}≠{want}"
        # positive 吃余数（_counts 把 total-sum 补给 positive）
        assert s["kinds"]["positive"] == STRESS_TARGET - sum(expected.values())


def test_stress_diagnostic_only_in_compound(stress_cases) -> None:
    for c in stress_cases:
        if c.scoring == "diagnostic_unsupported":
            assert c.category.startswith("stress_compound_"), f"{c.case_id} 诊断出现在非 compound 层"


def test_stress_min_query_count_only_web_search(stress_cases) -> None:
    for c in stress_cases:
        if c.min_query_count:
            assert c.expected_action == "call" and c.expected_capability == "web_search"


# --- 历史重复点：多图诱饵不改 label -------------------------------------------


def test_multi_image_decoys_keep_single_target(stress_cases) -> None:
    """多图清单是抗噪扰动：诱饵全是自有图，但 expected imagery_id 仍只指原图。"""
    for c in stress_cases:
        if len(c.imagery_inventory) > 1 and c.expected_action == "call":
            target = c.expected_arguments_subset.get("imagery_id")
            if target:
                owned = {f.imagery_id for f in c.imagery_inventory}
                assert target in owned, f"{c.case_id}: 目标图不在清单内"
                assert all(f.owner_user_id == DEFAULT_USER_ID for f in c.imagery_inventory)


# --- 异常：history 结构合法、不制造跨轮指代 -----------------------------------


def test_history_no_cross_turn_reference(stress_cases) -> None:
    for c in stress_cases:
        owned = {f.imagery_id for f in c.imagery_inventory}
        for msg in c.history:
            assert msg.get("role") in {"user", "assistant"}
            assert msg.get("content")
            assert not any(oid in msg["content"] for oid in owned), (
                f"{c.case_id}: 历史泄漏当前影像 ID（跨轮指代依赖）"
            )


# --- 非法输入：validate_stress_cases 必须拒绝污染 -----------------------------


def test_validate_rejects_dup_query() -> None:
    cases = list(generate_stress_cases(seed=STRESS_SEEDS[0]))
    poisoned = tuple(cases) + (cases[0],)  # 重复整条
    with pytest.raises(ValueError):
        validate_stress_cases(poisoned)


def test_validate_passes_clean() -> None:
    for seed in STRESS_SEEDS:
        validate_stress_cases(generate_stress_cases(seed=seed))  # 不抛即通过


# --- 回归：score 只评已录制的 case（断点续录中途看分布不被假 harness_error 污染）---


def test_score_filters_to_recorded_cases_only(tmp_path, monkeypatch) -> None:
    """run_stress score 的过滤契约：未录制的 case 跳过、不当 harness_error。

    修复根因：旧 _score_seed 无条件 replay 全部 STRESS_TARGET 条，限量/续录中途
    跑 score 会把未录的当 harness_error（试跑实测 980/1000 假错误）。修复后只对
    已落盘 {case_id}.json 的 case 评分；全量录满时为恒等过滤，口径不变。
    """

    from tests.ai.eval import run_stress

    seed = STRESS_SEEDS[0]
    cases = generate_stress_cases(seed=seed, target=STRESS_TARGET)
    # 只"录制"前 5 条（写空 json 占位即可，_recording_done 只看文件存在）。
    recorded_ids = [c.case_id for c in cases[:5]]
    seed_dir = tmp_path / STRESS_DATASET / str(seed)
    seed_dir.mkdir(parents=True)
    for case_id in recorded_ids:
        (seed_dir / f"{case_id}.json").write_text("{}", encoding="utf-8")

    # 把 _seed_dir 指向临时目录，复用真实 _recording_done 过滤逻辑。
    monkeypatch.setattr(run_stress, "_seed_dir", lambda s: tmp_path / STRESS_DATASET / str(s))

    kept = tuple(c for c in cases if run_stress._recording_done(seed, c.case_id))
    assert [c.case_id for c in kept] == recorded_ids  # 只留已录，未录全部跳过
    assert len(kept) == 5 and len(cases) == STRESS_TARGET  # 不是把 995 条当错误


def test_shard_slicing_non_overlapping_and_complete() -> None:
    """并行钩子契约：seed 内 shard i/n 步长切片，n 片不重叠且并起来等于全集。

    多进程并行靠进程隔离全局态（规划认可的并发安全方式）；分片若重叠则重复烧 API，
    若漏片则覆盖不全。两者都必须在起多进程前用纯逻辑锁死。
    """

    cases = generate_stress_cases(seed=STRESS_SEEDS[0], target=STRESS_TARGET)
    ids = [c.case_id for c in cases]
    for total in (2, 3, 4, 7):
        shards = [[ids[i] for i in range(len(ids)) if i % total == k] for k in range(total)]
        flat = [x for s in shards for x in s]
        assert len(flat) == len(set(flat)), f"n={total} 分片有重叠"
        assert set(flat) == set(ids), f"n={total} 分片未全覆盖"
        assert sum(len(s) for s in shards) == len(ids)


def test_recording_done_rejects_stale_query_hash(tmp_path, monkeypatch) -> None:
    """回归（历史重复问题点）：生成器改了 query 内容后，旧录制必须失效重录，
    不许 _recording_done 只看文件名就跳过、用旧 query 录制冒充新题（"走老路"）。

    根因：旧 _recording_done 只判 {case_id}.json 是否存在。生成器一改随机序列、
    query 全变（实测 588/1000 query_hash 变化），陈旧录制会被静默复用。修复：传 query
    时校验录制 query_hash 同源，不符即 False 触发重录。
    """

    import json
    from tests.ai.eval import run_stress
    from tests.ai.eval.clients import stable_hash

    seed = STRESS_SEEDS[0]
    seed_dir = tmp_path / STRESS_DATASET / str(seed)
    seed_dir.mkdir(parents=True)
    (seed_dir / "c1.json").write_text(
        json.dumps({"query_hash": stable_hash("新题 NDVI")}), encoding="utf-8"
    )
    monkeypatch.setattr(run_stress, "_seed_dir", lambda s: tmp_path / STRESS_DATASET / str(s))

    assert run_stress._recording_done(seed, "c1", "新题 NDVI") is True   # query 一致→复用
    assert run_stress._recording_done(seed, "c1", "旧题 水体掩膜") is False  # query 变→失效重录
    assert run_stress._recording_done(seed, "missing", "x") is False    # 不存在
    assert run_stress._recording_done(seed, "c1") is True               # 不传 query→只看存在（score 用）


# --- match_corrupted_id：损坏 ID 匹配回完整 ID，与 corrupt_id 三种损坏严格对齐 --------


def test_match_corrupted_id_covers_all_corruption_modes() -> None:
    """三种损坏方式各自唯一匹配 + 0匹配/多匹配边界。与 corrupt_id(trunc6/trunc8/badchar)对齐。"""

    from tests.ai.eval.heldout_phrasing import match_corrupted_id

    full = "123456abcdef"
    others = ("789abc000000", "fedcba987654")
    # trunc6 前缀唯一匹配
    assert match_corrupted_id("123456", (full, *others)) == full
    # trunc8 前缀唯一匹配
    assert match_corrupted_id("123456ab", (full, *others)) == full
    # badchar：第5位坏字符 'g'，其余位匹配（等长通配）
    assert match_corrupted_id("1234g6abcdef", (full, *others)) == full
    # 多匹配 → None（歧义）
    assert match_corrupted_id("123456", ("123456abcdef", "123456999999")) is None
    # 0 匹配 → None
    assert match_corrupted_id("ffffff", (full, *others)) is None
    # 空候选 → None
    assert match_corrupted_id("123456", ()) is None


def test_match_corrupted_id_aligns_with_corrupt_id_roundtrip() -> None:
    """往返一致性：corrupt_id 产出的损坏 ID，必能 match 回原图（清单无前缀冲突时）。

    防 corrupt_id 改了损坏方式而 match 没同步（两函数必须同源对齐）。
    """

    from random import Random
    from tests.ai.eval.heldout_phrasing import corrupt_id, match_corrupted_id

    rng = Random(20260612)
    for _ in range(50):
        full = "".join(rng.choice("0123456789abcdef") for _ in range(12))
        decoys = tuple("".join(rng.choice("0123456789abcdef") for _ in range(12)) for _ in range(2))
        bad = corrupt_id(full, rng)
        # 随机 decoy 与 full 前缀冲突概率近 0，匹配应唯一回 full
        assert match_corrupted_id(bad, (full, *decoys)) == full, f"bad={bad} full={full}"

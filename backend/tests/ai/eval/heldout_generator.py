"""heldout-v1 生成器：意图对象 → 自然语言 → 规则推导 label → 冻结 case。

纪律：
- 本模块禁止 import app.agent.llm_planner（不反向贴 prompt）。prompt_near 计算在 cases_generator。
- 配比 35/30/20/10/5；ID 来自 seed 确定性新池；label 由 derive_label 规则推导。
- 整句零重复：拒绝采样保证 1000 条 query 互不相同（防"题量虚胖"）。
- dataset_hash 由 (case_id, query, label) 指纹稳定计算，冻结后写 manifest。

层结构（target=1000）：
  positive      350  12 能力轮转，全部 call
  hard_negative 300  negation/concept/missing_id(空清单+指代两variant)/non_owner/general/contradiction
  boundary      200  8 个易混方向 × 方向化表达，全部 call
  compound      100  33 复合 web_search(主分,min_query_count=2) + 67 unsupported_multi(诊断)
  noise          50  25 脏文本+ID完整(call) + 25 ID损坏但清单有真图(none, 不许猜图)
"""

from __future__ import annotations

import json
from hashlib import sha256
from random import Random

from tests.ai.eval.cases import PlannerEvalCase
from tests.ai.eval.cases_generator import is_prompt_near
from tests.ai.eval.heldout_intents import (
    COMPOSITE_MODES,
    DST_CRS_POOL,
    INDEX_TYPES,
    POSITIVE_CAPABILITIES,
    HeldoutIdPool,
    IntentSpec,
    derive_label,
    imagery_inventory_for,
)
from tests.ai.eval import heldout_phrasing as phrasing


HELDOUT_V1_SEED = 20260610
HELDOUT_V1_TARGET = 1000
HELDOUT_DATASET = "heldout-v1"

# heldout-v2：全新 seed，验证修正后 derive_label 口径（多图前缀匹配 call/none 分流）+ #16 prompt。
# v1 已 sealed 退役为历史证据，v2 据修正口径重新冻结盲测（铁律3）。
HELDOUT_V2_SEED = 20260620
HELDOUT_V2_DATASET = "heldout-v2"

# 配比 35/30/20/10/5。
_RATIO = {
    "positive": 0.35,
    "hard_negative": 0.30,
    "boundary": 0.20,
    "compound": 0.10,
    "noise": 0.05,
}
_VALID_RATIO_TOL = 0.03

_DOC_CONTEXT = "用户已经上传了需要解析的 PDF/Word 文档。"

# case_id 前缀 → 层 kind（稳定映射，避免给 PlannerEvalCase 加冗余字段）。
_KIND_PREFIX = {
    "heldout_pos_": "positive",
    "heldout_neg_": "hard_negative",
    "heldout_bnd_": "boundary",
    "heldout_cmp_": "compound",
    "heldout_noise_": "noise",
}


def _kind_of(case) -> str:
    for prefix, kind in _KIND_PREFIX.items():
        if case.case_id.startswith(prefix):
            return kind
    return "unknown"


def _counts(total: int) -> dict[str, int]:
    counts = {kind: round(total * ratio) for kind, ratio in _RATIO.items()}
    counts["positive"] += total - sum(counts.values())  # 余数补给最大块
    return counts


class _UniqueQueries:
    """拒绝采样去重：render 闭包重抽随机直到 query 全局唯一。"""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def take(self, render, max_attempts: int = 60) -> str:
        for _ in range(max_attempts):
            result = render()
            query = result[0] if isinstance(result, tuple) else result
            if query not in self._seen:
                self._seen.add(query)
                return result
        raise ValueError("failed to render a unique heldout query; widen phrase banks")


def generate_heldout_cases(
    *, seed: int = HELDOUT_V1_SEED, target: int = HELDOUT_V1_TARGET, dataset: str = HELDOUT_DATASET
) -> tuple[PlannerEvalCase, ...]:
    rng = Random(seed)
    pool = HeldoutIdPool(rng)
    uniq = _UniqueQueries()
    counts = _counts(target)
    cases: list[PlannerEvalCase] = []
    cases += _gen_positive(counts["positive"], rng, pool, uniq, seed, dataset)
    cases += _gen_hard_negative(counts["hard_negative"], rng, pool, uniq, seed, dataset)
    cases += _gen_boundary(counts["boundary"], rng, pool, uniq, seed, dataset)
    cases += _gen_compound(counts["compound"], rng, pool, uniq, seed, dataset)
    cases += _gen_noise(counts["noise"], rng, pool, uniq, seed, dataset)
    return tuple(cases)


def _spec_arguments(rng: Random, capability: str) -> dict[str, object]:
    if capability == "calculate_spectral_index":
        return {"index_type": rng.choice(INDEX_TYPES)}
    if capability == "render_band_composite":
        return {"mode": rng.choice(COMPOSITE_MODES)}
    if capability == "clip_reproject_raster":
        return {"dst_crs": rng.choice(DST_CRS_POOL)}
    return {}


def _build_case(
    *,
    case_id: str,
    query: str,
    intent: IntentSpec,
    img: str | None,
    doc: str | None,
    seed: int,
    dataset: str,
    extra_imagery: tuple[str, ...] = (),
) -> PlannerEvalCase:
    inventory = imagery_inventory_for(intent.imagery_state, img)
    # 多图边界：追加诱饵自有图（指代/残缺ID 在多图下的歧义判定，验证修正后 derive_label 口径）。
    if extra_imagery:
        from tests.ai.eval.cases import ImageryFixture, DEFAULT_USER_ID

        inventory = inventory + tuple(
            ImageryFixture(iid, owner_user_id=DEFAULT_USER_ID) for iid in extra_imagery
        )
    label = derive_label(intent, imagery_id=img, document_id=doc, inventory=inventory)
    document_context = _DOC_CONTEXT if intent.document_state == "valid" else ""
    return PlannerEvalCase(
        case_id=case_id,
        query=query,
        expected_action=label.expected_action,  # type: ignore[arg-type]
        expected_capability=label.expected_capability,
        category=f"heldout_{intent.kind}_{intent.subtype}",
        notes=f"heldout-v1 场景生成；意图 {intent.kind}/{intent.subtype}。",
        imagery_inventory=inventory,
        document_context=document_context,
        expected_arguments_subset=dict(label.expected_arguments_subset),
        min_query_count=label.min_query_count,
        source="heldout",
        scoring=label.scoring,  # type: ignore[arg-type]
        prompt_near=is_prompt_near(query),
        dataset=dataset,
        seed=seed,
    )


def _gen_positive(total, rng, pool, uniq, seed, dataset):
    cases = []
    for i in range(total):
        cap = POSITIVE_CAPABILITIES[i % len(POSITIVE_CAPABILITIES)]
        args = _spec_arguments(rng, cap)
        if cap == "web_search":
            intent = IntentSpec("positive", f"pos_{cap}", "web_search")
            img = doc = None
        elif cap == "parse_document":
            doc = pool.new_document_id()
            intent = IntentSpec("positive", f"pos_{cap}", cap, document_state="valid")
            img = None
        else:
            img = pool.new_imagery_id()
            intent = IntentSpec("positive", f"pos_{cap}", cap, imagery_state="valid", arguments=args)
            doc = None
        query = uniq.take(lambda: phrasing.realize_positive(intent, img=img, doc=doc, rng=rng))
        cases.append(
            _build_case(
                case_id=f"heldout_pos_{cap}_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=doc,
                seed=seed,
                dataset=dataset,
            )
        )
    return cases


def _gen_hard_negative(total, rng, pool, uniq, seed, dataset):
    kinds = ("negation", "concept", "missing_id", "non_owner", "general", "contradiction")
    cases = []
    for i in range(total):
        kind = kinds[i % len(kinds)]
        img = doc = None
        extra: tuple[str, ...] = ()  # 多图诱饵自有图（missing_id 多图边界用）
        if kind == "negation":
            # 半数清单里放一张真图加大诱惑；allow_tool=False 决定 label=none。
            with_image = (i // len(kinds)) % 2 == 1
            img = pool.new_imagery_id() if with_image else None
            state = "valid" if with_image else "none"
            intent = IntentSpec("hard_negative", "negation", "calculate_ndvi", imagery_state=state, allow_tool=False)
            query = uniq.take(lambda: phrasing.realize_negation(rng))
        elif kind == "concept":
            img = pool.new_imagery_id()
            intent = IntentSpec("hard_negative", "concept", None, imagery_state="valid")
            query = uniq.take(lambda: phrasing.realize_concept(rng))
        elif kind == "missing_id":
            # 两个 variant 交替：空清单 / 清单有真图但只用指代词（压"不许自动映射唯一影像"）。
            pronoun_variant = (i // len(kinds)) % 2 == 1
            # 先 render 拿 query 实际写的 task，再据 task 定 capability（不再写死 calculate_ndvi）。
            query, task = uniq.take(lambda: phrasing.realize_missing_id(rng, pronoun_variant=pronoun_variant))
            cap, cap_args = phrasing.task_capability(task)
            if pronoun_variant:
                img = pool.new_imagery_id()
                # 多图变体（交替）：追加诱饵图 → 纯指代多图歧义 → none；单图 → 补全 call。
                if (i // (len(kinds) * 2)) % 2 == 1:
                    extra = (pool.new_imagery_id(), pool.new_imagery_id())
                intent = IntentSpec("hard_negative", "missing_id_pronoun", cap,
                                    imagery_state="unreferenced", arguments=cap_args)
            else:
                intent = IntentSpec("hard_negative", "missing_id_empty", cap,
                                    imagery_state="none", arguments=cap_args)
        elif kind == "non_owner":
            img = pool.new_imagery_id()
            intent = IntentSpec("hard_negative", "non_owner", "calculate_ndvi", imagery_state="non_owner")
            query = uniq.take(lambda: phrasing.realize_non_owner(rng, img=img))
        elif kind == "general":
            intent = IntentSpec("hard_negative", "general", None)
            query = uniq.take(lambda: phrasing.realize_general(rng))
        else:  # contradiction
            img = pool.new_imagery_id()
            doc = pool.new_document_id()
            intent = IntentSpec("hard_negative", "contradiction", None, imagery_state="valid")
            query = uniq.take(lambda: phrasing.realize_contradiction(rng, img=img, doc=doc))
        cases.append(
            _build_case(
                case_id=f"heldout_neg_{kind}_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=doc,
                seed=seed,
                dataset=dataset,
                extra_imagery=extra,
            )
        )
    return cases


def _gen_boundary(total, rng, pool, uniq, seed, dataset):
    directions = tuple(phrasing.BOUNDARY_DIRECTIONS)
    cases = []
    for i in range(total):
        direction = directions[i % len(directions)]
        cap, args = phrasing.BOUNDARY_DIRECTIONS[direction]
        if cap == "parse_document":
            doc = pool.new_document_id()
            img = None
            intent = IntentSpec("boundary", direction, cap, document_state="valid")
        else:
            img = pool.new_imagery_id()
            doc = None
            intent = IntentSpec("boundary", direction, cap, imagery_state="valid", arguments=dict(args))
        query = uniq.take(lambda: phrasing.realize_boundary(direction, img=img, doc=doc, rng=rng))
        cases.append(
            _build_case(
                case_id=f"heldout_bnd_{direction}_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=doc,
                seed=seed,
                dataset=dataset,
            )
        )
    return cases


def _gen_compound(total, rng, pool, uniq, seed, dataset):
    """复合层：1/3 复合 web_search（计主分，min_query_count=2），2/3 多工具并行（诊断块）。"""

    web_count = total // 3
    multi_count = total - web_count
    cases = []
    for i in range(web_count):
        intent = IntentSpec("compound", "web_search_multi", "web_search")
        query = uniq.take(lambda: phrasing.realize_compound_web(rng))
        cases.append(
            _build_case(
                case_id=f"heldout_cmp_web_{i:03d}",
                query=query,
                intent=intent,
                img=None,
                doc=None,
                seed=seed,
                dataset=dataset,
            )
        )
    for i in range(multi_count):
        img = pool.new_imagery_id()
        intent = IntentSpec("compound", "unsupported_multi_tool", None, imagery_state="valid")
        query = uniq.take(lambda: phrasing.realize_unsupported_multi(rng, img=img))
        cases.append(
            _build_case(
                case_id=f"heldout_cmp_multi_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=None,
                seed=seed,
                dataset=dataset,
            )
        )
    return cases


def _gen_noise(total, rng, pool, uniq, seed, dataset):
    """噪声层两分叉：
    dirty  = 脏文本但 ID 完整 → label 按干净意图推导（call），测抗噪；
    badid  = 清单有真图、查询里 ID 损坏 → none，测"不许猜图/不许自动补全"。
    """

    dirty_count = total // 2
    badid_count = total - dirty_count
    cases = []
    dirty_caps = ("calculate_ndvi", "detect_objects", "raster_inspect")
    for i in range(dirty_count):
        cap = dirty_caps[i % len(dirty_caps)]
        img = pool.new_imagery_id()
        intent = IntentSpec("noise", f"dirty_{cap}", cap, imagery_state="valid")
        query = uniq.take(
            lambda: phrasing.realize_noise(
                phrasing.realize_positive(intent, img=img, doc=None, rng=rng), rng
            )
        )
        cases.append(
            _build_case(
                case_id=f"heldout_noise_dirty_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=None,
                seed=seed,
                dataset=dataset,
            )
        )
    for i in range(badid_count):
        img = pool.new_imagery_id()  # 清单里的真图
        bad_id = phrasing.corrupt_id(img, rng)  # 查询里的损坏 ID
        # 先 render 拿 query 实际写的 task，再据 task 定 capability（不再写死 calculate_ndvi）。
        query, task = uniq.take(lambda: phrasing.realize_corrupted_id(rng, bad_id=bad_id))
        cap, cap_args = phrasing.task_capability(task)
        # provided_imagery_ref=bad_id：多图时 derive_label 用它做唯一前缀匹配（终裁口径）。
        intent = IntentSpec("noise", "corrupted_id", cap, imagery_state="invalid",
                            provided_imagery_ref=bad_id, arguments=cap_args)
        # 三类边界轮转：单图→call / 多图唯一前缀匹配→call / 多图多匹配→none（验证修正口径）。
        extra: tuple[str, ...] = ()
        variant = i % 3
        if variant == 1:
            extra = (pool.new_imagery_id(),)  # 随机诱饵，bad_id 仍唯一匹配真图 → call
        elif variant == 2:
            # 诱饵图与真图共享 bad_id 前缀 → 多匹配歧义 → none
            collide = bad_id[:6] + pool.new_imagery_id()[6:]
            extra = (collide,)
        cases.append(
            _build_case(
                case_id=f"heldout_noise_badid_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=None,
                seed=seed,
                dataset=dataset,
                extra_imagery=extra,
            )
        )
    return cases


def validate_heldout_cases(cases) -> None:
    """heldout 按层独立校验（不走 dev-set 的 validate_cases）。

    校验：整句零重复、配比 35/30/20/10/5±tol、source/dataset 一致、capability 合法、
    diagnostic 仅出现在 compound、min_query_count 仅用于 web_search call、
    ID 不复用 dev-set 常量。违反即抛 ValueError。
    """

    from tests.ai.eval.cases import (
        DOCUMENT_ID as _DOC,
        OTHER_IMAGERY_ID as _OTHER,
        PRIMARY_IMAGERY_ID as _PRIMARY,
        valid_capability_names,
    )

    valid_names = valid_capability_names()
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_queries: set[str] = set()
    kind_counts: dict[str, int] = {}
    forbidden_ids = {_PRIMARY, _OTHER, _DOC}

    for case in cases:
        if case.case_id in seen_ids:
            errors.append(f"duplicate case_id: {case.case_id}")
        seen_ids.add(case.case_id)
        if case.query in seen_queries:
            errors.append(f"{case.case_id}: duplicate query text (题量虚胖)")
        seen_queries.add(case.query)
        if case.source != "heldout":
            errors.append(f"{case.case_id}: heldout case must have source=heldout, got {case.source}")
        if not case.dataset:
            errors.append(f"{case.case_id}: heldout case must set dataset")
        if case.expected_action == "call" and case.expected_capability not in valid_names:
            errors.append(f"{case.case_id}: unknown capability {case.expected_capability}")
        if case.expected_action == "none" and case.expected_capability is not None:
            errors.append(f"{case.case_id}: none action must not set capability")
        if any(bad in case.query for bad in forbidden_ids):
            errors.append(f"{case.case_id}: must not reuse dev-set ID constants")
        if case.min_query_count and (
            case.expected_action != "call" or case.expected_capability != "web_search"
        ):
            errors.append(f"{case.case_id}: min_query_count only valid for web_search calls")
        kind = _kind_of(case)
        if case.scoring == "diagnostic_unsupported" and kind != "compound":
            errors.append(f"{case.case_id}: diagnostic scoring only allowed in compound layer")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1

    total = len(cases)
    if total:
        for kind, ratio in _RATIO.items():
            actual = kind_counts.get(kind, 0) / total
            if abs(actual - ratio) > _VALID_RATIO_TOL:
                errors.append(f"heldout {kind} ratio {actual:.3f} off target {ratio:.2f}")

    if errors:
        raise ValueError("; ".join(errors[:40]) + (f"; ...({len(errors)} total)" if len(errors) > 40 else ""))


def heldout_fingerprint(cases) -> str:
    payload = [
        {
            "case_id": c.case_id,
            "query": c.query,
            "expected_action": c.expected_action,
            "expected_capability": c.expected_capability,
            "arguments": c.expected_arguments_subset,
            "min_query_count": c.min_query_count,
            "scoring": c.scoring,
            "category": c.category,
            "prompt_near": c.prompt_near,
        }
        for c in cases
    ]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def dataset_hash(cases) -> str:
    return sha256(heldout_fingerprint(cases).encode("utf-8")).hexdigest()


def heldout_summary(cases) -> dict[str, object]:
    from collections import Counter

    kinds = Counter(_kind_of(c) for c in cases)
    subtypes = Counter(c.category for c in cases)
    return {
        "total": len(cases),
        "kinds": dict(sorted(kinds.items())),
        "subtypes": dict(sorted(subtypes.items())),
        "prompt_near": sum(1 for c in cases if c.prompt_near),
        "diagnostic_unsupported": sum(1 for c in cases if c.scoring == "diagnostic_unsupported"),
        "expected_none": sum(1 for c in cases if c.expected_action == "none"),
        "expected_call": sum(1 for c in cases if c.expected_action == "call"),
        "unique_queries": len({c.query for c in cases}),
    }

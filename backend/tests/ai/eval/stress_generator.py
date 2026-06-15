"""random-stress 生成器：多 seed 随机压力集（看分布，不固化、不封存）。

与 heldout-v1 的区别：
- 不冻结、不封存：每个 seed 现生成现跑，重点是**跨 seed 的分布**（均值/最差/方差），
  不是单次密封成绩。某 seed 暴露问题→记录 seed+case→复现后再决定是否进 dev-set。
- 三个 heldout 没有的扰动轴：多图清单（诱饵自有影像）、长 document_context、历史消息干扰。
  其余轴（同义/错别字/缺标点/ID 损坏/指代缺失）复用 heldout_phrasing。

不作弊纪律（与 heldout 同源）：
- label 全部由 derive_label 规则推导；扰动要么**保持答案**（错别字/多图/历史/长文 → 抗噪测试），
  要么把变化烤进 imagery_state（损坏 ID→invalid→none，指代→unreferenced→none），由 derive_label 重算。
- 历史干扰只放**不同 ID/话题**的旧轮次，当前 query 自包含——绝不制造跨轮指代依赖
  （那是 prompt 本身的灰区，断言任一答案都是错标）。
- 本模块禁止 import app.agent.llm_planner（不反向贴 prompt）。
- 整句零重复（拒绝采样），防"题量虚胖"。
"""

from __future__ import annotations

import json
from hashlib import sha256
from random import Random

from tests.ai.eval.cases import DEFAULT_USER_ID, ImageryFixture, PlannerEvalCase
from tests.ai.eval.cases_generator import is_prompt_near
from tests.ai.eval.heldout_intents import (
    COMPOSITE_MODES,
    DST_CRS_POOL,
    INDEX_TYPES,
    HeldoutIdPool,
    IntentSpec,
    derive_label,
    imagery_inventory_for,
)
from tests.ai.eval import heldout_phrasing as phrasing


STRESS_TARGET = 1000  # 每 seed 1000 条：低样本量下偶发问题会被噪声淹没，足量才看得到真问题
STRESS_SEEDS: tuple[int, ...] = (40010, 40020, 40030)  # 首轮 3 seed（3×1000=3000 次调用）
STRESS_DATASET = "random-stress"

# 层配比与 heldout 一致（35/30/20/10/5），但每 seed 现采、叠加更猛的随机扰动。
_RATIO = {
    "positive": 0.35,
    "hard_negative": 0.30,
    "boundary": 0.20,
    "compound": 0.10,
    "noise": 0.05,
}

_DOC_CONTEXT_SHORT = "用户已经上传了需要解析的 PDF/Word 文档。"

# 长 document_context 填充（测长上下文抗噪；只是系统提示噪声，不改 label）。
_DOC_LONG_FILLER = (
    "本报告由自然资源调查中心编制，涵盖区域土地利用现状、生态保护红线、耕地占补平衡、"
    "城镇开发边界与地质灾害隐患点排查等多个章节。第一章总述调查范围与技术路线；"
    "第二章列出遥感影像源、分辨率与时相；第三章给出分类体系与精度评价指标；"
    "后续章节逐项展开统计表与专题地图说明。附录包含术语表、参考坐标系与数据字典。"
)

# 历史消息干扰池：与当前 query 不同话题/ID，纯噪声，不制造跨轮指代依赖。
_HISTORY_DISTRACTORS: tuple[tuple[dict[str, str], ...], ...] = (
    (
        {"role": "user", "content": "什么是 NDVI？原理给我讲讲"},
        {"role": "assistant", "content": "NDVI 是归一化植被指数，反映植被覆盖与长势。"},
    ),
    (
        {"role": "user", "content": "帮我推荐两本遥感入门书"},
        {"role": "assistant", "content": "可以看《遥感导论》和《数字图像处理》。"},
    ),
    (
        {"role": "user", "content": "后天上海天气怎么样"},
        {"role": "assistant", "content": "建议出行前再查一次实时预报。"},
    ),
    (
        {"role": "user", "content": "刚才那景图先不用管了"},
        {"role": "assistant", "content": "好的，已暂停之前的处理。"},
    ),
    ({"role": "user", "content": "谢谢，你很专业"},),
)


def _maybe_multi_image(
    base: tuple[ImageryFixture, ...],
    pool: HeldoutIdPool,
    rng: Random,
    prob: float = 0.5,
) -> tuple[ImageryFixture, ...]:
    """对自有影像清单随机追加 1-3 张诱饵自有影像（不改 label：query 仍只指名原 ID）。

    仅当原清单非空且首图属当前用户时追加；非属主/空清单不动，避免改变语义。
    """

    if not base or base[0].owner_user_id != DEFAULT_USER_ID:
        return base
    if rng.random() >= prob:
        return base
    decoys = tuple(
        ImageryFixture(pool.new_imagery_id(), owner_user_id=DEFAULT_USER_ID)
        for _ in range(rng.randint(1, 3))
    )
    items = list(base) + list(decoys)
    rng.shuffle(items)  # 打乱顺序，别让真图总在首位
    return tuple(items)


def _maybe_history(rng: Random, prob: float = 0.4) -> tuple[dict[str, str], ...]:
    """随机返回一段历史干扰（不同话题/ID）。空元组=不加历史。"""

    if rng.random() >= prob:
        return ()
    return tuple(dict(m) for m in rng.choice(_HISTORY_DISTRACTORS))


def _doc_context(intent: IntentSpec, rng: Random) -> str:
    """parse_document 有效时随机给短/长文档上下文（长文测长上下文抗噪）。"""

    if intent.document_state != "valid":
        return ""
    if rng.random() < 0.5:
        return _DOC_LONG_FILLER + "\n" + _DOC_CONTEXT_SHORT
    return _DOC_CONTEXT_SHORT


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
    inventory: tuple[ImageryFixture, ...],
    document_context: str,
    history: tuple[dict[str, str], ...],
    seed: int,
) -> PlannerEvalCase:
    label = derive_label(intent, imagery_id=img, document_id=doc, inventory=inventory)
    return PlannerEvalCase(
        case_id=case_id,
        query=query,
        expected_action=label.expected_action,  # type: ignore[arg-type]
        expected_capability=label.expected_capability,
        category=f"stress_{intent.kind}_{intent.subtype}",
        notes=f"random-stress seed={seed}；意图 {intent.kind}/{intent.subtype}。",
        imagery_inventory=inventory,
        document_context=document_context,
        history=history,
        expected_arguments_subset=dict(label.expected_arguments_subset),
        min_query_count=label.min_query_count,
        source="random_stress",
        scoring=label.scoring,  # type: ignore[arg-type]
        prompt_near=is_prompt_near(query),
        dataset=STRESS_DATASET,
        seed=seed,
    )


class _UniqueQueries:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def take(self, render, max_attempts: int = 80) -> str:
        for _ in range(max_attempts):
            result = render()
            query = result[0] if isinstance(result, tuple) else result
            if query not in self._seen:
                self._seen.add(query)
                return result
        raise ValueError("failed to render unique stress query; widen banks")


def _counts(total: int) -> dict[str, int]:
    counts = {kind: round(total * ratio) for kind, ratio in _RATIO.items()}
    counts["positive"] += total - sum(counts.values())
    return counts


def generate_stress_cases(*, seed: int, target: int = STRESS_TARGET) -> tuple[PlannerEvalCase, ...]:
    """单 seed 现采压力集。不同 seed → 不同题面与扰动组合（看分布用）。"""

    rng = Random(seed)
    pool = HeldoutIdPool(rng)
    uniq = _UniqueQueries()
    counts = _counts(target)
    cases: list[PlannerEvalCase] = []
    cases += _gen_positive(counts["positive"], rng, pool, uniq, seed)
    cases += _gen_hard_negative(counts["hard_negative"], rng, pool, uniq, seed)
    cases += _gen_boundary(counts["boundary"], rng, pool, uniq, seed)
    cases += _gen_compound(counts["compound"], rng, pool, uniq, seed)
    cases += _gen_noise(counts["noise"], rng, pool, uniq, seed)
    return tuple(cases)


def _gen_positive(total, rng, pool, uniq, seed):
    caps = phrasing.POSITIVE_BANKS  # 12 能力全覆盖
    cap_names = tuple(caps)
    cases = []
    for i in range(total):
        cap = cap_names[i % len(cap_names)]
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
        # 正向题随机叠错别字（realize_positive 内置）+ 偶发去标点，测抗噪不改 label。
        def render():
            base = phrasing.realize_positive(intent, img=img, doc=doc, rng=rng)
            if rng.random() < 0.3:
                base = base.replace("，", " ")
            return base
        query = uniq.take(render)
        inventory = _maybe_multi_image(imagery_inventory_for(intent.imagery_state, img), pool, rng)
        cases.append(
            _build_case(
                case_id=f"stress_pos_{cap}_{seed}_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=doc,
                inventory=inventory,
                document_context=_doc_context(intent, rng),
                history=_maybe_history(rng),
                seed=seed,
            )
        )
    return cases


def _gen_hard_negative(total, rng, pool, uniq, seed):
    kinds = ("negation", "concept", "missing_id", "non_owner", "general", "contradiction")
    cases = []
    for i in range(total):
        kind = kinds[i % len(kinds)]
        img = doc = None
        if kind == "negation":
            with_image = rng.random() < 0.5
            img = pool.new_imagery_id() if with_image else None
            state = "valid" if with_image else "none"
            intent = IntentSpec("hard_negative", "negation", "calculate_ndvi", imagery_state=state, allow_tool=False)
            render = lambda: phrasing.realize_negation(rng)
        elif kind == "concept":
            img = pool.new_imagery_id()
            intent = IntentSpec("hard_negative", "concept", None, imagery_state="valid")
            render = lambda: phrasing.realize_concept(rng)
        elif kind == "missing_id":
            pronoun = rng.random() < 0.5
            # 先 render 拿到 query 实际写的 task，再据 task 定 capability（不再写死 calculate_ndvi）。
            query, task = uniq.take(lambda: phrasing.realize_missing_id(rng, pronoun_variant=pronoun))
            cap, cap_args = phrasing.task_capability(task)
            if pronoun:
                img = pool.new_imagery_id()
                intent = IntentSpec("hard_negative", "missing_id_pronoun", cap,
                                    imagery_state="unreferenced", arguments=cap_args)
            else:
                intent = IntentSpec("hard_negative", "missing_id_empty", cap,
                                    imagery_state="none", arguments=cap_args)
            render = None  # query 已生成
        elif kind == "non_owner":
            img = pool.new_imagery_id()
            intent = IntentSpec("hard_negative", "non_owner", "calculate_ndvi", imagery_state="non_owner")
            render = lambda: phrasing.realize_non_owner(rng, img=img)
        elif kind == "general":
            intent = IntentSpec("hard_negative", "general", None)
            render = lambda: phrasing.realize_general(rng)
        else:
            img = pool.new_imagery_id()
            doc = pool.new_document_id()
            intent = IntentSpec("hard_negative", "contradiction", None, imagery_state="valid")
            render = lambda: phrasing.realize_contradiction(rng, img=img, doc=doc)
        if render is not None:
            query = uniq.take(render)
        inventory = _maybe_multi_image(imagery_inventory_for(intent.imagery_state, img), pool, rng)
        cases.append(
            _build_case(
                case_id=f"stress_neg_{kind}_{seed}_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=doc,
                inventory=inventory,
                document_context="",
                history=_maybe_history(rng),
                seed=seed,
            )
        )
    return cases


def _gen_boundary(total, rng, pool, uniq, seed):
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
        inventory = _maybe_multi_image(imagery_inventory_for(intent.imagery_state, img), pool, rng)
        cases.append(
            _build_case(
                case_id=f"stress_bnd_{direction}_{seed}_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=doc,
                inventory=inventory,
                document_context=_doc_context(intent, rng),
                history=_maybe_history(rng),
                seed=seed,
            )
        )
    return cases


def _gen_compound(total, rng, pool, uniq, seed):
    """1/3 复合 web_search（主分,min_query_count=2），2/3 多工具并行（诊断）。"""

    web_count = total // 3
    multi_count = total - web_count
    cases = []
    for i in range(web_count):
        intent = IntentSpec("compound", "web_search_multi", "web_search")
        query = uniq.take(lambda: phrasing.realize_compound_web(rng))
        cases.append(
            _build_case(
                case_id=f"stress_cmp_web_{seed}_{i:03d}",
                query=query,
                intent=intent,
                img=None,
                doc=None,
                inventory=(),
                document_context="",
                history=_maybe_history(rng),
                seed=seed,
            )
        )
    for i in range(multi_count):
        img = pool.new_imagery_id()
        intent = IntentSpec("compound", "unsupported_multi_tool", None, imagery_state="valid")
        query = uniq.take(lambda: phrasing.realize_unsupported_multi(rng, img=img))
        inventory = _maybe_multi_image(imagery_inventory_for(intent.imagery_state, img), pool, rng)
        cases.append(
            _build_case(
                case_id=f"stress_cmp_multi_{seed}_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=None,
                inventory=inventory,
                document_context="",
                history=_maybe_history(rng),
                seed=seed,
            )
        )
    return cases


def _gen_noise(total, rng, pool, uniq, seed):
    """dirty=脏文本+ID完整(call) ; badid=清单有真图+查询ID损坏(none,不许猜图)。"""

    dirty_count = total // 2
    badid_count = total - dirty_count
    cases = []
    dirty_caps = ("calculate_ndvi", "detect_objects", "raster_inspect", "extract_water_mask")
    for i in range(dirty_count):
        cap = dirty_caps[i % len(dirty_caps)]
        img = pool.new_imagery_id()
        intent = IntentSpec("noise", f"dirty_{cap}", cap, imagery_state="valid")
        query = uniq.take(
            lambda: phrasing.realize_noise(
                phrasing.realize_positive(intent, img=img, doc=None, rng=rng), rng
            )
        )
        inventory = _maybe_multi_image(imagery_inventory_for(intent.imagery_state, img), pool, rng)
        cases.append(
            _build_case(
                case_id=f"stress_noise_dirty_{seed}_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=None,
                inventory=inventory,
                document_context="",
                history=_maybe_history(rng),
                seed=seed,
            )
        )
    for i in range(badid_count):
        img = pool.new_imagery_id()
        bad_id = phrasing.corrupt_id(img, rng)
        # 先 render 拿 query 实际写的 task，再据 task 定 capability（不再写死 calculate_ndvi）。
        query, task = uniq.take(lambda: phrasing.realize_corrupted_id(rng, bad_id=bad_id))
        cap, cap_args = phrasing.task_capability(task)
        # provided_imagery_ref=bad_id：多图时 derive_label 用它做唯一前缀匹配（终裁口径）。
        intent = IntentSpec("noise", "corrupted_id", cap, imagery_state="invalid",
                            provided_imagery_ref=bad_id, arguments=cap_args)
        inventory = _maybe_multi_image(imagery_inventory_for(intent.imagery_state, img), pool, rng)
        cases.append(
            _build_case(
                case_id=f"stress_noise_badid_{seed}_{i:03d}",
                query=query,
                intent=intent,
                img=img,
                doc=None,
                inventory=inventory,
                document_context="",
                history=_maybe_history(rng),
                seed=seed,
            )
        )
    return cases


def validate_stress_cases(cases) -> None:
    """单 seed 压力集校验：整句零重复、source/dataset 一致、label 可由 derive_label 重算、
    ID 不复用 dev-set 常量、history 不制造跨轮指代依赖（结构合法）。违反即 ValueError。"""

    from tests.ai.eval.cases import (
        DOCUMENT_ID as _DOC,
        OTHER_IMAGERY_ID as _OTHER,
        PRIMARY_IMAGERY_ID as _PRIMARY,
        valid_capability_names,
    )

    valid_names = valid_capability_names()
    forbidden = {_PRIMARY, _OTHER, _DOC}
    errors: list[str] = []
    seen_ids: set[str] = set()
    seen_q: set[str] = set()

    for c in cases:
        if c.case_id in seen_ids:
            errors.append(f"dup case_id {c.case_id}")
        seen_ids.add(c.case_id)
        if c.query in seen_q:
            errors.append(f"{c.case_id}: dup query (题量虚胖)")
        seen_q.add(c.query)
        if c.source != "random_stress":
            errors.append(f"{c.case_id}: source must be random_stress")
        if c.dataset != STRESS_DATASET:
            errors.append(f"{c.case_id}: dataset must be {STRESS_DATASET}")
        if c.expected_action == "call" and c.expected_capability not in valid_names:
            errors.append(f"{c.case_id}: unknown capability {c.expected_capability}")
        if c.expected_action == "none" and c.expected_capability is not None:
            errors.append(f"{c.case_id}: none must not set capability")
        if any(bad in c.query for bad in forbidden):
            errors.append(f"{c.case_id}: reuses dev-set ID constant")
        # 历史干扰必须是合法 role/content 且不含当前题的真图 ID（防跨轮指代）。
        owned = {f.imagery_id for f in c.imagery_inventory}
        for msg in c.history:
            if msg.get("role") not in {"user", "assistant"} or not msg.get("content"):
                errors.append(f"{c.case_id}: malformed history message")
            if any(oid in msg.get("content", "") for oid in owned):
                errors.append(f"{c.case_id}: history leaks current imagery id (跨轮指代)")
    if errors:
        raise ValueError("; ".join(errors[:40]) + (f"; ...({len(errors)})" if len(errors) > 40 else ""))


def stress_fingerprint(cases) -> str:
    payload = [
        {"case_id": c.case_id, "query": c.query, "action": c.expected_action,
         "cap": c.expected_capability, "args": c.expected_arguments_subset,
         "scoring": c.scoring, "category": c.category}
        for c in cases
    ]
    return sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def stress_summary(cases) -> dict[str, object]:
    from collections import Counter

    kinds = Counter(c.category.split("_")[1] if "_" in c.category else "?" for c in cases)
    return {
        "total": len(cases),
        "expected_call": sum(1 for c in cases if c.expected_action == "call"),
        "expected_none": sum(1 for c in cases if c.expected_action == "none"),
        "diagnostic": sum(1 for c in cases if c.scoring == "diagnostic_unsupported"),
        "with_history": sum(1 for c in cases if c.history),
        "multi_image": sum(1 for c in cases if len(c.imagery_inventory) > 1),
        "prompt_near": sum(1 for c in cases if c.prompt_near),
        "unique_queries": len({c.query for c in cases}),
        "kinds": dict(sorted(kinds.items())),
    }

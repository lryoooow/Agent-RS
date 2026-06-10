from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import replace
from itertools import cycle
from typing import Iterable

from tests.ai.eval.cases import (
    DOCUMENT_ID,
    OTHER_IMAGE,
    OTHER_IMAGERY_ID,
    OWNED_IMAGE,
    PRIMARY_IMAGERY_ID,
    PlannerEvalCase,
)


GENERATED_CASE_COUNT = 300
PROMPT_NEAR_THRESHOLD = 0.72

FEW_SHOT_QUERIES: tuple[str, ...] = (
    "你好",
    "什么是 NDVI？",
    "这张图的 NDVI 是什么意思？",
    "明天杭州有中雨吗？",
    "明天上海天气怎么样？我想过去自驾游，给我一份两天一夜计划",
    "计算影像 94e758f38ede 的 NDVI",
    "检查影像 94e758f38ede 的波段和 CRS",
    "算一下影像 94e758f38ede 的 NBR",
    "用真彩色显示影像 94e758f38ede",
    "检测影像 94e758f38ede 里的飞机和船只",
    "把影像 94e758f38ede 做地物分割",
    "给影像 94e758f38ede 做云掩膜/去云质检",
    "提取影像 94e758f38ede 里的水体/圈出水域范围",
    "把影像 94e758f38ede 重投影到 EPSG:4326 / 按范围裁剪",
    "识别影像 94e758f38ede 上的文字 / 读出这张扫描地图里的注记",
    "总结文档 3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071 / 把整篇文档的要点列出来",
    "计算刚才那张图的 NDVI，但没有可用影像 ID",
)


def generate_generated_cases(target_count: int = GENERATED_CASE_COUNT) -> tuple[PlannerEvalCase, ...]:
    counts = _target_counts(target_count)
    cases = (
        _generate_simple(counts["simple"])
        + _generate_none(counts["none"])
        + _generate_multiple(counts["multiple"])
        + _generate_parallel(counts["parallel"])
    )
    return tuple(_with_prompt_near(case) for case in cases)


def generation_summary(cases: Iterable[PlannerEvalCase]) -> dict[str, object]:
    generated = [case for case in cases if case.source == "generated"]
    buckets = Counter(_bucket(case) for case in generated)
    return {
        "total": len(generated),
        "buckets": dict(sorted(buckets.items())),
        "none_ratio": _ratio(buckets.get("none", 0), len(generated)),
        "prompt_near": sum(1 for case in generated if case.prompt_near),
        "diagnostic_unsupported": sum(
            1 for case in generated if case.scoring == "diagnostic_unsupported"
        ),
    }


def stable_case_fingerprint(cases: Iterable[PlannerEvalCase]) -> str:
    payload = []
    for case in cases:
        payload.append(
            {
                "case_id": case.case_id,
                "query": case.query,
                "expected_action": case.expected_action,
                "expected_capability": case.expected_capability,
                "category": case.category,
                "arguments": case.expected_arguments_subset,
                "min_query_count": case.min_query_count,
                "source": case.source,
                "scoring": case.scoring,
                "prompt_near": case.prompt_near,
            }
        )
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def is_prompt_near(query: str, threshold: float = PROMPT_NEAR_THRESHOLD) -> bool:
    query_tokens = _tokens(query)
    if not query_tokens:
        return False
    return any(_jaccard(query_tokens, _tokens(example)) >= threshold for example in FEW_SHOT_QUERIES)


def _target_counts(target_count: int) -> dict[str, int]:
    none = max(math.ceil(target_count * 0.30), round(target_count * 0.30))
    simple = round(target_count * 0.40)
    multiple = round(target_count * 0.15)
    parallel = target_count - simple - none - multiple
    if parallel < 0:
        raise ValueError(f"target_count too small: {target_count}")
    return {"simple": simple, "none": none, "multiple": multiple, "parallel": parallel}


def _generate_simple(total: int) -> tuple[PlannerEvalCase, ...]:
    slugs = (
        "raster_inspect",
        "calculate_ndvi",
        "calculate_spectral_index",
        "render_band_composite",
        "cloud_shadow_mask",
        "extract_water_mask",
        "clip_reproject_raster",
        "detect_objects",
        "segment_landcover",
        "ocr_recognize",
        "parse_document",
    )
    counts: Counter[str] = Counter()
    cases: list[PlannerEvalCase] = []
    for slug in cycle(slugs):
        if len(cases) >= total:
            break
        counts[slug] += 1
        cases.append(_simple_case(slug, counts[slug]))
    return tuple(cases)


def _simple_case(slug: str, index: int) -> PlannerEvalCase:
    img = PRIMARY_IMAGERY_ID
    if slug == "raster_inspect":
        term = _pick(("元数据", "波段数量", "CRS 和范围", "像元尺寸"), index)
        query = _pick(
            (
                "检查影像 {img} 的{term}",
                "帮我看一下影像 {img} 的{term}信息",
                "读取 {img} 的{term}",
            ),
            index,
        ).format(img=img, term=term)
        return _case(
            f"gen_raster_inspect_simple_{index:03d}",
            query,
            "call",
            "raster_inspect",
            expected_arguments_subset={"imagery_id": img},
        )
    if slug == "calculate_ndvi":
        term = _pick(("NDVI", "植被指数", "植被覆盖情况", "归一化植被指数"), index)
        query = _pick(
            (
                "计算影像 {img} 的 {term}",
                "帮我跑一下 {img} 的{term}",
                "{img} 这张图的{term}结果给我",
            ),
            index,
        ).format(img=img, term=term)
        return _case(
            f"gen_ndvi_simple_{index:03d}",
            query,
            "call",
            "calculate_ndvi",
            expected_arguments_subset={"imagery_id": img},
        )
    if slug == "calculate_spectral_index":
        term, index_type = _pick(
            (
                ("NBR 火烧迹地指数", "nbr"),
                ("NDWI 水体指数", "ndwi"),
                ("NDBI 建筑指数", "ndbi"),
                ("EVI 增强植被指数", "evi"),
                ("SAVI 土壤调节植被指数", "savi"),
                ("NDMI 水分指数", "ndmi"),
            ),
            index,
        )
        query = _pick(
            (
                "给影像 {img} 计算 {term}",
                "我需要 {img} 的{term}",
                "跑一下影像 {img} 的{term}",
            ),
            index,
        ).format(img=img, term=term)
        return _case(
            f"gen_spectral_index_simple_{index:03d}",
            query,
            "call",
            "calculate_spectral_index",
            expected_arguments_subset={"imagery_id": img, "index_type": index_type},
        )
    if slug == "render_band_composite":
        term, mode = _pick(
            (("真彩色预览", "true_color"), ("假彩色预览", "false_color"), ("RGB 波段组合", "true_color")),
            index,
        )
        query = _pick(
            (
                "把影像 {img} 渲染成{term}",
                "用{term}显示影像 {img}",
                "生成 {img} 的{term}",
            ),
            index,
        ).format(img=img, term=term)
        return _case(
            f"gen_band_composite_simple_{index:03d}",
            query,
            "call",
            "render_band_composite",
            expected_arguments_subset={"imagery_id": img, "mode": mode},
        )
    if slug == "cloud_shadow_mask":
        term = _pick(("云检测", "云阴影掩膜", "去云质检", "云和阴影区域"), index)
        query = _pick(
            (
                "对影像 {img} 做{term}",
                "检查 {img} 里的{term}",
                "帮我给 {img} 生成{term}",
            ),
            index,
        ).format(img=img, term=term)
        return _case(
            f"gen_cloud_mask_simple_{index:03d}",
            query,
            "call",
            "cloud_shadow_mask",
            expected_arguments_subset={"imagery_id": img},
        )
    if slug == "extract_water_mask":
        term = _pick(("提取水体", "识别河流湖泊水库", "圈定水域", "生成水体掩膜"), index)
        query = _pick(
            (
                "对影像 {img} {term}",
                "帮我从 {img} 里{term}",
                "{img} 这张图需要{term}",
            ),
            index,
        ).format(img=img, term=term)
        return _case(
            f"gen_water_mask_simple_{index:03d}",
            query,
            "call",
            "extract_water_mask",
            expected_arguments_subset={"imagery_id": img},
        )
    if slug == "clip_reproject_raster":
        crs = _pick(("EPSG:4326", "EPSG:3857", "EPSG:32650"), index)
        term = _pick(("重投影", "转坐标系", "按范围裁切后重投影"), index)
        query = _pick(
            (
                "把影像 {img} {term}到 {crs}",
                "将 {img} 转成 {crs}",
                "对影像 {img} 做{term}，目标坐标系 {crs}",
            ),
            index,
        ).format(img=img, term=term, crs=crs)
        return _case(
            f"gen_clip_reproject_simple_{index:03d}",
            query,
            "call",
            "clip_reproject_raster",
            expected_arguments_subset={"imagery_id": img, "dst_crs": crs},
        )
    if slug == "detect_objects":
        target = _pick(("飞机", "舰船", "车辆", "储油罐", "桥梁"), index)
        query = _pick(
            (
                "检测影像 {img} 中的{target}目标",
                "找出 {img} 里的{target}",
                "帮我识别影像 {img} 可能存在的{target}",
            ),
            index,
        ).format(img=img, target=target)
        return _case(
            f"gen_detect_objects_simple_{index:03d}",
            query,
            "call",
            "detect_objects",
            expected_arguments_subset={"imagery_id": img},
        )
    if slug == "segment_landcover":
        target = _pick(("地物分割", "建筑林地水体分区", "土地覆盖分类", "地表类别分割"), index)
        query = _pick(
            (
                "把影像 {img} 做{target}",
                "对 {img} 进行{target}",
                "生成影像 {img} 的{target}结果",
            ),
            index,
        ).format(img=img, target=target)
        return _case(
            f"gen_segment_landcover_simple_{index:03d}",
            query,
            "call",
            "segment_landcover",
            expected_arguments_subset={"imagery_id": img},
        )
    if slug == "ocr_recognize":
        term = _pick(("影像文字", "扫描地图注记", "地名标注", "图上文字"), index)
        query = _pick(
            (
                "识别影像 {img} 上的{term}",
                "读出 {img} 里的{term}",
                "帮我提取影像 {img} 中的{term}",
            ),
            index,
        ).format(img=img, term=term)
        return _case(
            f"gen_ocr_simple_{index:03d}",
            query,
            "call",
            "ocr_recognize",
            expected_arguments_subset={"imagery_id": img},
        )
    if slug == "parse_document":
        term = _pick(("总结重点", "概括全文", "提取章节要点", "整理表格和标题"), index)
        query = _pick(
            (
                "总结文档 {doc} 的{term}",
                "帮我{term}，文档 ID 是 {doc}",
                "读取文档 {doc} 并{term}",
            ),
            index,
        ).format(doc=DOCUMENT_ID, term=term)
        return _case(
            f"gen_parse_document_simple_{index:03d}",
            query,
            "call",
            "parse_document",
            document_context="用户已经上传了需要解析的 PDF/Word 文档。",
            expected_arguments_subset={"document_id": DOCUMENT_ID},
        )
    raise ValueError(f"unknown simple slug: {slug}")


def _generate_none(total: int) -> tuple[PlannerEvalCase, ...]:
    kinds = ("negation", "concept", "missing_id", "non_owner", "general", "contradiction")
    counts: Counter[str] = Counter()
    cases: list[PlannerEvalCase] = []
    for kind in cycle(kinds):
        if len(cases) >= total:
            break
        counts[kind] += 1
        cases.append(_none_case(kind, counts[kind]))
    return tuple(cases)


def _none_case(kind: str, index: int) -> PlannerEvalCase:
    img = PRIMARY_IMAGERY_ID
    if kind == "negation":
        term = _pick(("NDVI", "水体指数", "云掩膜", "目标检测", "地物分割"), index)
        query = _pick(
            (
                "我不要算{term}，只想知道它是什么",
                "先别调用工具，解释一下{term}的含义",
                "不要对影像 {img} 跑{term}，只讲原理",
            ),
            index,
        ).format(img=img, term=term)
        return _case(f"gen_none_negation_{index:03d}", query, "none", None, category="none_negation")
    if kind == "concept":
        term = _pick(("近红外波段", "NDVI", "假彩色", "云阴影", "NBR 指数"), index)
        query = _pick(
            (
                "影像 {img} 的{term}通常代表什么？",
                "{term}在遥感分析里有什么意义？",
                "只解释一下 {img} 相关的{term}，不要计算",
            ),
            index,
        ).format(img=img, term=term)
        return _case(
            f"gen_none_concept_{index:03d}",
            query,
            "none",
            None,
            category="none_concept",
            imagery_inventory=OWNED_IMAGE,
        )
    if kind == "missing_id":
        task = _pick(("NDVI", "水体掩膜", "地物分割", "云检测", "重投影"), index)
        query = _pick(
            (
                "计算刚才那张图的{task}",
                "给这张影像做{task}，但我没有提供影像 ID",
                "帮我处理上面那张图的{task}",
            ),
            index,
        ).format(task=task)
        return _case(f"gen_none_missing_id_{index:03d}", query, "none", None, category="none_missing_id")
    if kind == "non_owner":
        task = _pick(("NDVI", "水体掩膜", "云阴影掩膜", "目标检测", "重投影"), index)
        query = "请对影像 {img} 做{task}".format(img=OTHER_IMAGERY_ID, task=task)
        return _case(
            f"gen_edge_non_owner_{index:03d}",
            query,
            "none",
            None,
            category="edge_non_owner",
            imagery_inventory=OTHER_IMAGE,
        )
    if kind == "general":
        query = _pick(
            (
                "帮我写一段遥感项目周报摘要",
                "把 remote sensing 翻译成中文",
                "用 Python 写一个排序函数",
                "解释一下什么是监督学习",
                "帮我算 2468 加 1357",
            ),
            index,
        )
        return _case(f"gen_none_general_{index:03d}", query, "none", None, category="none_general")
    if kind == "contradiction":
        query = _pick(
            (
                "用 NDVI 算法检测影像 {img} 里的船只",
                "用云掩膜工具总结文档 {doc}",
                "用 OCR 判断 {img} 的植被覆盖率",
                "用重投影功能识别 {img} 里的车辆",
            ),
            index,
        ).format(img=img, doc=DOCUMENT_ID)
        return _case(
            f"gen_none_contradiction_{index:03d}",
            query,
            "none",
            None,
            category="none_contradiction",
            imagery_inventory=OWNED_IMAGE,
        )
    raise ValueError(f"unknown none kind: {kind}")


def _generate_multiple(total: int) -> tuple[PlannerEvalCase, ...]:
    builders = (
        _multiple_water_mask,
        _multiple_spectral_water,
        _multiple_ocr,
        _multiple_detect,
        _multiple_inspect,
        _multiple_segment,
        _multiple_cloud,
        _multiple_composite,
        _multiple_clip,
    )
    counts: Counter[str] = Counter()
    cases: list[PlannerEvalCase] = []
    for builder in cycle(builders):
        if len(cases) >= total:
            break
        name = builder.__name__
        counts[name] += 1
        cases.append(builder(counts[name]))
    return tuple(cases)


def _multiple_water_mask(index: int) -> PlannerEvalCase:
    query = _pick(
        (
            "我关注影像 {img} 的水域边界，不要只给指数，直接圈出水体范围",
            "{img} 里河流湖泊在哪，给我水体掩膜结果",
        ),
        index,
    ).format(img=PRIMARY_IMAGERY_ID)
    return _case(
        f"gen_multiple_water_mask_{index:03d}",
        query,
        "call",
        "extract_water_mask",
        category="multiple",
        expected_arguments_subset={"imagery_id": PRIMARY_IMAGERY_ID},
    )


def _multiple_spectral_water(index: int) -> PlannerEvalCase:
    query = _pick(
        (
            "我不是要水域矢量边界，只要影像 {img} 的 NDWI 指数",
            "评估 {img} 的水体指数，用 NDWI 就行",
        ),
        index,
    ).format(img=PRIMARY_IMAGERY_ID)
    return _case(
        f"gen_multiple_spectral_water_{index:03d}",
        query,
        "call",
        "calculate_spectral_index",
        category="multiple",
        expected_arguments_subset={"imagery_id": PRIMARY_IMAGERY_ID, "index_type": "ndwi"},
    )


def _multiple_ocr(index: int) -> PlannerEvalCase:
    query = _pick(
        (
            "识别影像 {img} 里的地图文字标注，不是识别飞机车辆",
            "读出 {img} 上的地名和道路注记",
        ),
        index,
    ).format(img=PRIMARY_IMAGERY_ID)
    return _case(
        f"gen_multiple_ocr_{index:03d}",
        query,
        "call",
        "ocr_recognize",
        category="multiple",
        expected_arguments_subset={"imagery_id": PRIMARY_IMAGERY_ID},
    )


def _multiple_detect(index: int) -> PlannerEvalCase:
    query = _pick(
        (
            "识别影像 {img} 中的飞机目标，不是读文字",
            "找出 {img} 机场附近可能的车辆和飞机",
        ),
        index,
    ).format(img=PRIMARY_IMAGERY_ID)
    return _case(
        f"gen_multiple_detect_{index:03d}",
        query,
        "call",
        "detect_objects",
        category="multiple",
        expected_arguments_subset={"imagery_id": PRIMARY_IMAGERY_ID},
    )


def _multiple_inspect(index: int) -> PlannerEvalCase:
    query = _pick(
        (
            "先别分析地物，查看影像 {img} 的波段、CRS 和范围",
            "我只需要 {img} 的元数据和波段信息",
        ),
        index,
    ).format(img=PRIMARY_IMAGERY_ID)
    return _case(
        f"gen_multiple_inspect_{index:03d}",
        query,
        "call",
        "raster_inspect",
        category="multiple",
        expected_arguments_subset={"imagery_id": PRIMARY_IMAGERY_ID},
    )


def _multiple_segment(index: int) -> PlannerEvalCase:
    query = _pick(
        (
            "不要只检测单个目标，把影像 {img} 做成地物类别分区",
            "我需要 {img} 的建筑、林地、水体等地物分割",
        ),
        index,
    ).format(img=PRIMARY_IMAGERY_ID)
    return _case(
        f"gen_multiple_segment_{index:03d}",
        query,
        "call",
        "segment_landcover",
        category="multiple",
        expected_arguments_subset={"imagery_id": PRIMARY_IMAGERY_ID},
    )


def _multiple_cloud(index: int) -> PlannerEvalCase:
    query = _pick(
        (
            "影像 {img} 看起来有云，先做云阴影掩膜质检",
            "我想检查 {img} 是否被云和阴影污染",
        ),
        index,
    ).format(img=PRIMARY_IMAGERY_ID)
    return _case(
        f"gen_multiple_cloud_{index:03d}",
        query,
        "call",
        "cloud_shadow_mask",
        category="multiple",
        expected_arguments_subset={"imagery_id": PRIMARY_IMAGERY_ID},
    )


def _multiple_composite(index: int) -> PlannerEvalCase:
    mode = _pick(("true_color", "false_color"), index)
    term = "真彩色" if mode == "true_color" else "假彩色"
    query = "我现在只想看影像 {img} 的{term}显示，不做检测或分割".format(
        img=PRIMARY_IMAGERY_ID,
        term=term,
    )
    return _case(
        f"gen_multiple_composite_{index:03d}",
        query,
        "call",
        "render_band_composite",
        category="multiple",
        expected_arguments_subset={"imagery_id": PRIMARY_IMAGERY_ID, "mode": mode},
    )


def _multiple_clip(index: int) -> PlannerEvalCase:
    crs = _pick(("EPSG:4326", "EPSG:3857"), index)
    query = "不要分析内容，先把影像 {img} 转到 {crs} 坐标系".format(
        img=PRIMARY_IMAGERY_ID,
        crs=crs,
    )
    return _case(
        f"gen_multiple_clip_{index:03d}",
        query,
        "call",
        "clip_reproject_raster",
        category="multiple",
        expected_arguments_subset={"imagery_id": PRIMARY_IMAGERY_ID, "dst_crs": crs},
    )


def _generate_parallel(total: int) -> tuple[PlannerEvalCase, ...]:
    web_count = max(1, total // 3)
    unsupported_count = total - web_count
    return _parallel_web_search(web_count) + _unsupported_multi_tool(unsupported_count)


def _parallel_web_search(total: int) -> tuple[PlannerEvalCase, ...]:
    specs = (
        (
            "weather_travel",
            "明天南京天气怎么样？如果适合出行，再给我一个两天自驾计划",
            2,
        ),
        (
            "policy_dataset",
            "查一下最新自然资源遥感政策，同时找几个公开洪水遥感数据集",
            2,
        ),
        (
            "price_official",
            "看看最近卫星影像云服务价格变化，并找一下官方产品说明",
            2,
        ),
    )
    cases: list[PlannerEvalCase] = []
    counts: Counter[str] = Counter()
    for spec in cycle(specs):
        if len(cases) >= total:
            break
        slug, query, min_query_count = spec
        counts[slug] += 1
        suffix = counts[slug]
        cases.append(
            _case(
                f"gen_parallel_web_search_{slug}_{suffix:03d}",
                query,
                "call",
                "web_search",
                category="parallel_web_search",
                min_query_count=min_query_count,
            )
        )
    return tuple(cases)


def _unsupported_multi_tool(total: int) -> tuple[PlannerEvalCase, ...]:
    templates = (
        "对影像 {img} 同时计算 NDVI 并提取水体掩膜",
        "先给影像 {img} 做云掩膜，再马上做地物分割",
        "把影像 {img} 重投影后再检测飞机和船只",
        "同时读取影像 {img} 的文字注记并计算 NBR 指数",
        "对影像 {img} 一次完成真彩色预览和目标检测",
    )
    cases = []
    for index in range(1, total + 1):
        query = _pick(templates, index).format(img=PRIMARY_IMAGERY_ID)
        cases.append(
            _case(
                f"gen_unsupported_multi_tool_{index:03d}",
                query,
                "none",
                None,
                category="unsupported_multi_tool",
                imagery_inventory=OWNED_IMAGE,
                scoring="diagnostic_unsupported",
                notes="系统当前 TaskSelector 只支持单 capability，真并行多工具请求只进诊断块。",
            )
        )
    return tuple(cases)


def _case(
    case_id: str,
    query: str,
    expected_action: str,
    expected_capability: str | None,
    *,
    category: str = "simple",
    notes: str = "程序化生成的 planner 路由评测样本。",
    imagery_inventory=OWNED_IMAGE,
    document_context: str = "",
    expected_arguments_subset: dict[str, object] | None = None,
    min_query_count: int = 0,
    scoring: str = "main",
) -> PlannerEvalCase:
    if expected_capability == "parse_document" or expected_arguments_subset == {"document_id": DOCUMENT_ID}:
        imagery_inventory = ()
    if expected_capability == "web_search":
        imagery_inventory = ()
    return PlannerEvalCase(
        case_id=case_id,
        query=query,
        expected_action=expected_action,  # type: ignore[arg-type]
        expected_capability=expected_capability,
        category=category,
        notes=notes,
        imagery_inventory=tuple(imagery_inventory),
        document_context=document_context,
        expected_arguments_subset=dict(expected_arguments_subset or {}),
        min_query_count=min_query_count,
        source="generated",
        scoring=scoring,  # type: ignore[arg-type]
    )


def _with_prompt_near(case: PlannerEvalCase) -> PlannerEvalCase:
    return replace(case, prompt_near=is_prompt_near(case.query))


def _pick(items, index: int):
    return items[(index - 1) % len(items)]


def _bucket(case: PlannerEvalCase) -> str:
    if case.category == "simple":
        return "simple"
    if case.category.startswith("none") or case.category.startswith("edge"):
        return "none"
    if case.category == "multiple":
        return "multiple"
    if case.category in {"parallel_web_search", "unsupported_multi_tool"}:
        return "parallel"
    return case.category


def _ratio(count: int, total: int) -> float:
    return (count / total) if total else 0.0


def _tokens(text: str) -> set[str]:
    text = text.lower()
    tokens: set[str] = set()
    current: list[str] = []
    for char in text:
        if "\u4e00" <= char <= "\u9fff":
            if current:
                tokens.add("".join(current))
                current.clear()
            tokens.add(char)
        elif char.isalnum():
            current.append(char)
        else:
            if current:
                tokens.add("".join(current))
                current.clear()
    if current:
        tokens.add("".join(current))
    return tokens


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)

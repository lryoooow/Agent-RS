"""heldout-v1 意图对象与规则推导（场景先行的 ground truth 源头）。

设计纪律（对应规划五条铁律 + 防作弊约束）：
- label 不手填：expected_action / capability / arguments 全部由 IntentSpec 经 derive_label 规则推导。
- ID 不复用 dev-set 常量：新 ID 池由 seed 确定性生成，断言排除 PRIMARY/OTHER/DOCUMENT_ID。
- 本模块禁止 import app.agent.llm_planner._planner_prompt（题库不得反向贴 prompt）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from random import Random

from tests.ai.eval.cases import (
    DEFAULT_USER_ID,
    DOCUMENT_ID,
    OTHER_USER_ID,
    OTHER_IMAGERY_ID,
    PRIMARY_IMAGERY_ID,
    ImageryFixture,
)


# 工具需要的关键参数取值域（与 cases_generator 重叠是业务事实，非模板抄袭）。
INDEX_TYPES: tuple[str, ...] = ("nbr", "ndwi", "ndbi", "evi", "savi", "ndmi")
COMPOSITE_MODES: tuple[str, ...] = ("true_color", "false_color")
DST_CRS_POOL: tuple[str, ...] = ("EPSG:4326", "EPSG:3857", "EPSG:32650", "EPSG:32649")

# 单工具正向覆盖目标：11 tools + web_search 全覆盖。
POSITIVE_CAPABILITIES: tuple[str, ...] = (
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
    "web_search",
)

# 需要有效自有影像才能执行的工具（缺/非属主/无效 → none）。
_IMAGERY_TOOLS: frozenset[str] = frozenset(
    {
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
    }
)


@dataclass(frozen=True)
class IntentSpec:
    """用户意图的结构化真值。自然语言表达是它的下游，不是它的来源。

    imagery_state 语义：
      valid        查询明确写出自有影像 ID → 可执行
      non_owner    查询写出他人影像 ID → none（validator 拦截属兜底）
      invalid      查询里的 ID 是损坏/截断的 → 按最终自有影像清单判定；唯一匹配可补全，多图歧义为 none
      unreferenced 查询只用指代词没写 ID → 按最终自有影像清单判定；唯一图可补全，多图歧义为 none
      none         清单为空且查询没写 ID → none
    """

    kind: str  # positive | hard_negative | boundary | compound | noise
    subtype: str  # 更细的报告分类
    wants: str | None  # 目标 capability；None=闲聊/概念/通用任务
    imagery_state: str = "none"  # valid | non_owner | invalid | unreferenced | none
    document_state: str = "none"  # valid | none
    prior_analysis_state: str = "none"  # has | none —— 本对话此前是否已产出分析结果（report 判定维度）
    allow_tool: bool = True  # 用户是否允许调用工具（否定诱导=False）
    user_denies_id: bool = False  # 用户显式声明未提供影像 ID；优先级高于清单唯一图
    provided_imagery_ref: str | None = None  # 用户 query 里写的残缺/损坏 ID（invalid 态用于多图前缀匹配）
    arguments: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DerivedLabel:
    expected_action: str
    expected_capability: str | None
    expected_arguments_subset: dict[str, object]
    scoring: str
    min_query_count: int = 0


def derive_label(
    intent: IntentSpec,
    *,
    imagery_id: str | None,
    document_id: str | None,
    inventory: tuple[ImageryFixture, ...] = (),
) -> DerivedLabel:
    """从意图对象规则推导 label。任何用例的标注都必须能由此函数重算（防手填漂移）。"""

    # 不支持的并行多工具：系统只支持单 capability，恒为 none，只进诊断块。
    if intent.subtype == "unsupported_multi_tool":
        return DerivedLabel("none", None, {}, "diagnostic_unsupported")
    # 用户明确不许调用工具（否定/只讲原理）。
    if not intent.allow_tool:
        return DerivedLabel("none", None, {}, "main")
    # 概念问答 / 通用写作翻译代码数学 / 工具语义矛盾：无明确可执行意图。
    if intent.wants is None:
        return DerivedLabel("none", None, {}, "main")
    if intent.wants == "web_search":
        # 复合检索要求多 query 结构（与 dev-set parallel_web_search 同口径，structure-only）。
        min_queries = 2 if intent.subtype == "web_search_multi" else 0
        return DerivedLabel("call", "web_search", {}, "main", min_query_count=min_queries)
    if intent.wants == "parse_document":
        if intent.document_state != "valid" or not document_id:
            return DerivedLabel("none", None, {}, "main")
        return DerivedLabel("call", "parse_document", {"document_id": document_id}, "main")
    if intent.wants == "generate_report":
        # 报告通道：不吃 imagery_id/document_id，只看本对话此前是否已产出分析结果。
        # 有分析史 → call generate_report；无分析史（凭空要报告）→ none（与 planner no_analysis_to_report 同口径）。
        if intent.prior_analysis_state != "has":
            return DerivedLabel("none", None, {}, "main")
        return DerivedLabel("call", "generate_report", {}, "main")
    if intent.wants in _IMAGERY_TOOLS:
        if intent.user_denies_id:
            return DerivedLabel("none", None, {}, "main")
        target_imagery_id: str | None = None
        if intent.imagery_state == "valid" and imagery_id:
            target_imagery_id = imagery_id
        elif intent.imagery_state in {"invalid", "unreferenced"}:
            owned = [item for item in inventory if item.owner_user_id == DEFAULT_USER_ID]
            if len(owned) == 1:
                target_imagery_id = owned[0].imagery_id  # 唯一图：指代/残缺都补全这张
            elif intent.provided_imagery_ref:
                # 多图 + 残缺 ID：能唯一前缀/坏字符匹配到一张才补全，否则歧义 none（终裁口径）。
                from tests.ai.eval.heldout_phrasing import match_corrupted_id

                target_imagery_id = match_corrupted_id(
                    intent.provided_imagery_ref,
                    tuple(item.imagery_id for item in owned),
                )
            # 多图 + 纯指代（无 provided_imagery_ref）→ target 仍 None → none
        if not target_imagery_id:
            return DerivedLabel("none", None, {}, "main")
        args: dict[str, object] = {"imagery_id": target_imagery_id}
        args.update(intent.arguments)
        return DerivedLabel("call", intent.wants, args, "main")
    raise ValueError(f"unknown wants capability: {intent.wants}")


class HeldoutIdPool:
    """seed 确定性 ID 池：新 12-hex 影像 ID + UUID 文档 ID，断言排除 dev-set 常量。"""

    _FORBIDDEN_IMAGERY = frozenset({PRIMARY_IMAGERY_ID, OTHER_IMAGERY_ID})

    def __init__(self, rng: Random) -> None:
        self._rng = rng
        self._used_imagery: set[str] = set()
        self._used_document: set[str] = set()

    def new_imagery_id(self) -> str:
        while True:
            candidate = "".join(self._rng.choice("0123456789abcdef") for _ in range(12))
            if candidate in self._FORBIDDEN_IMAGERY or candidate in self._used_imagery:
                continue
            self._used_imagery.add(candidate)
            return candidate

    def new_document_id(self) -> str:
        while True:
            hex_chars = "".join(self._rng.choice("0123456789abcdef") for _ in range(32))
            candidate = (
                f"{hex_chars[:8]}-{hex_chars[8:12]}-{hex_chars[12:16]}-"
                f"{hex_chars[16:20]}-{hex_chars[20:]}"
            )
            if candidate == DOCUMENT_ID or candidate in self._used_document:
                continue
            self._used_document.add(candidate)
            return candidate


def imagery_inventory_for(state: str, imagery_id: str | None) -> tuple[ImageryFixture, ...]:
    """按影像状态构造 fixture。

    valid        → 清单含该自有影像
    non_owner    → 清单含该影像但属他人
    invalid      → 清单含一张**真实自有影像**（imagery_id 传真图 ID；查询里写的是损坏 ID）
    unreferenced → 清单含一张**真实自有影像**（查询只用指代词）
    none         → 空清单
    """

    if state in {"valid", "invalid", "unreferenced"} and imagery_id:
        return (ImageryFixture(imagery_id, owner_user_id=DEFAULT_USER_ID),)
    if state == "non_owner" and imagery_id:
        return (ImageryFixture(imagery_id, owner_user_id=OTHER_USER_ID),)
    return ()

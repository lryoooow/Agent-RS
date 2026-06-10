from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from app.agent.capability_registry import AGENT_CAPABILITIES
from app.agent.routing import ALL_CANDIDATE_TOOLS, AgentRoute
from app.agent.tool_registry import TOOLS


EvalAction = Literal["none", "call"]
# source: golden=手写锚点(prompt-near 风险高), generated=模板批量产出
EvalSource = Literal["golden", "generated"]
# scoring: main=计入主准确率; diagnostic_unsupported=系统暂不支持(如多工具并行), 只进诊断块
EvalScoring = Literal["main", "diagnostic_unsupported"]

DEFAULT_USER_ID = "00000000-0000-4000-8000-000000000001"
OTHER_USER_ID = "00000000-0000-4000-8000-000000000002"
PRIMARY_IMAGERY_ID = "94e758f38ede"
OTHER_IMAGERY_ID = "aaaaaaaaaaaa"
DOCUMENT_ID = "11111111-1111-1111-1111-111111111111"


@dataclass(frozen=True)
class ImageryFixture:
    imagery_id: str
    owner_user_id: str = DEFAULT_USER_ID
    band_count: int = 6
    width: int = 256
    height: int = 256
    crs: str = "EPSG:4326"


def default_route() -> AgentRoute:
    return AgentRoute(
        mode="full_pipeline",
        reason="planner_eval",
        candidate_tools=ALL_CANDIDATE_TOOLS,
        candidate_agents=("web_search",),
    )


@dataclass(frozen=True)
class PlannerEvalCase:
    case_id: str
    query: str
    expected_action: EvalAction
    expected_capability: str | None
    category: str
    notes: str
    user_id: str | None = DEFAULT_USER_ID
    imagery_inventory: tuple[ImageryFixture, ...] = ()
    document_context: str = ""
    route: AgentRoute = field(default_factory=default_route)
    expected_arguments_subset: dict[str, object] = field(default_factory=dict)
    # web_search 复合检索只在确定性评测里校验多 query 结构；语义质量留给独立 judge 诊断。
    min_query_count: int = 0
    source: EvalSource = "golden"
    scoring: EvalScoring = "main"
    prompt_near: bool = False
    use_memory: bool = False
    use_rag: bool = False

    @property
    def conversation_id(self) -> str:
        return f"planner-eval-{self.case_id}"


OWNED_IMAGE = (ImageryFixture(PRIMARY_IMAGERY_ID),)
OTHER_IMAGE = (ImageryFixture(OTHER_IMAGERY_ID, owner_user_id=OTHER_USER_ID),)


GOLDEN_CASES: tuple[PlannerEvalCase, ...] = (
    PlannerEvalCase(
        case_id="tool_raster_inspect",
        query=f"检查影像 {PRIMARY_IMAGERY_ID} 的波段数量、CRS 和范围",
        expected_action="call",
        expected_capability="raster_inspect",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="影像质检应选择 raster_inspect。",
    ),
    PlannerEvalCase(
        case_id="tool_ndvi",
        query=f"请计算影像 {PRIMARY_IMAGERY_ID} 的 NDVI",
        expected_action="call",
        expected_capability="calculate_ndvi",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="明确 NDVI 计算。",
    ),
    PlannerEvalCase(
        case_id="tool_spectral_nbr",
        query=f"算一下影像 {PRIMARY_IMAGERY_ID} 的 NBR 火烧迹地指数",
        expected_action="call",
        expected_capability="calculate_spectral_index",
        imagery_inventory=OWNED_IMAGE,
        expected_arguments_subset={"index_type": "nbr"},
        category="tool_positive",
        notes="需要关键参数 index_type=nbr。",
    ),
    PlannerEvalCase(
        case_id="tool_spectral_ndwi",
        query=f"给影像 {PRIMARY_IMAGERY_ID} 计算 NDWI 水体指数",
        expected_action="call",
        expected_capability="calculate_spectral_index",
        imagery_inventory=OWNED_IMAGE,
        expected_arguments_subset={"index_type": "ndwi"},
        category="tool_positive",
        notes="光谱指数分支，校验 index_type=ndwi。",
    ),
    PlannerEvalCase(
        case_id="tool_band_true_color",
        query=f"用真彩色方式显示影像 {PRIMARY_IMAGERY_ID}",
        expected_action="call",
        expected_capability="render_band_composite",
        imagery_inventory=OWNED_IMAGE,
        expected_arguments_subset={"mode": "true_color"},
        category="tool_positive",
        notes="真彩色合成。",
    ),
    PlannerEvalCase(
        case_id="tool_band_false_color",
        query=f"把影像 {PRIMARY_IMAGERY_ID} 渲染成假彩色预览",
        expected_action="call",
        expected_capability="render_band_composite",
        imagery_inventory=OWNED_IMAGE,
        expected_arguments_subset={"mode": "false_color"},
        category="tool_positive",
        notes="假彩色合成。",
    ),
    PlannerEvalCase(
        case_id="tool_cloud_mask",
        query=f"对影像 {PRIMARY_IMAGERY_ID} 做云和阴影掩膜质检",
        expected_action="call",
        expected_capability="cloud_shadow_mask",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="预处理云阴影掩膜。",
    ),
    PlannerEvalCase(
        case_id="tool_water_mask",
        query=f"提取影像 {PRIMARY_IMAGERY_ID} 里的水体范围",
        expected_action="call",
        expected_capability="extract_water_mask",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="水体掩膜提取。",
    ),
    PlannerEvalCase(
        case_id="tool_clip_reproject",
        query=f"把影像 {PRIMARY_IMAGERY_ID} 重投影到 EPSG:4326",
        expected_action="call",
        expected_capability="clip_reproject_raster",
        imagery_inventory=OWNED_IMAGE,
        expected_arguments_subset={"dst_crs": "EPSG:4326"},
        category="tool_positive",
        notes="裁剪/重投影工具，校验 dst_crs。",
    ),
    PlannerEvalCase(
        case_id="tool_segment_landcover",
        query=f"把影像 {PRIMARY_IMAGERY_ID} 做地物分割",
        expected_action="call",
        expected_capability="segment_landcover",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="分割领域工具。",
    ),
    PlannerEvalCase(
        case_id="tool_detect_objects",
        query=f"检测影像 {PRIMARY_IMAGERY_ID} 中的飞机和船只目标",
        expected_action="call",
        expected_capability="detect_objects",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="目标检测领域工具。",
    ),
    PlannerEvalCase(
        case_id="tool_parse_document",
        query=f"总结文档 {DOCUMENT_ID} 的重点",
        expected_action="call",
        expected_capability="parse_document",
        document_context="用户已经上传了需要总结的 PDF/Word 文档。",
        category="tool_positive",
        notes="文档解析工具吃 document_id。",
    ),
    PlannerEvalCase(
        case_id="tool_ocr_recognize",
        query=f"识别影像 {PRIMARY_IMAGERY_ID} 上的文字和扫描地图注记",
        expected_action="call",
        expected_capability="ocr_recognize",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="OCR 走影像通道，但领域归 document_agent。",
    ),
    PlannerEvalCase(
        case_id="search_weather",
        query="明天杭州会下中雨吗？",
        expected_action="call",
        expected_capability="web_search",
        category="web_search",
        notes="天气具有时效性，应联网。",
    ),
    PlannerEvalCase(
        case_id="search_latest_policy",
        query="最近国家自然资源部发布了哪些遥感相关政策？",
        expected_action="call",
        expected_capability="web_search",
        category="web_search",
        notes="最新政策需要外部信息。",
    ),
    PlannerEvalCase(
        case_id="search_compound_weather_travel",
        query="明天上海天气怎么样？我想自驾过去，顺便给我一个两天一晚计划",
        expected_action="call",
        expected_capability="web_search",
        category="web_search",
        notes="复合意图，天气和攻略都需要外部信息。",
    ),
    PlannerEvalCase(
        case_id="search_latest_dataset",
        query="帮我查一下 2026 年最新公开洪水遥感数据集",
        expected_action="call",
        expected_capability="web_search",
        category="web_search",
        notes="最新数据集需要联网核验。",
    ),
    PlannerEvalCase(
        case_id="none_greeting",
        query="你好",
        expected_action="none",
        expected_capability=None,
        category="none",
        notes="闲聊不应触发能力。",
    ),
    PlannerEvalCase(
        case_id="none_ndvi_concept",
        query="什么是 NDVI？",
        expected_action="none",
        expected_capability=None,
        imagery_inventory=OWNED_IMAGE,
        category="none",
        notes="概念解释，即使有影像也不应计算。",
    ),
    PlannerEvalCase(
        case_id="none_missing_imagery",
        query="计算这张影像的 NDVI",
        expected_action="none",
        expected_capability=None,
        category="none",
        notes="没有可用 imagery_id，不允许猜测。",
    ),
    PlannerEvalCase(
        case_id="none_translation",
        query="把 hello remote sensing 翻译成中文",
        expected_action="none",
        expected_capability=None,
        category="none",
        notes="普通翻译不应调用工具。",
    ),
    PlannerEvalCase(
        case_id="none_writing",
        query="帮我写一段遥感项目周报摘要",
        expected_action="none",
        expected_capability=None,
        category="none",
        notes="普通写作不应调用工具。",
    ),
    PlannerEvalCase(
        case_id="none_programming",
        query="帮我写一个 Python 快速排序函数",
        expected_action="none",
        expected_capability=None,
        category="none",
        notes="代码生成不应调用遥感工具或联网。",
    ),
    PlannerEvalCase(
        case_id="none_math",
        query="帮我计算 123 + 456",
        expected_action="none",
        expected_capability=None,
        category="none",
        notes="普通数学不应调用能力。",
    ),
    PlannerEvalCase(
        case_id="none_band_concept_with_image",
        query=f"影像 {PRIMARY_IMAGERY_ID} 的近红外波段通常有什么意义？",
        expected_action="none",
        expected_capability=None,
        imagery_inventory=OWNED_IMAGE,
        category="none",
        notes="概念问答不应因为出现影像 ID 就触发工具。",
    ),
    PlannerEvalCase(
        case_id="edge_non_owner_imagery",
        query=f"计算影像 {OTHER_IMAGERY_ID} 的 NDVI",
        expected_action="none",
        expected_capability=None,
        imagery_inventory=OTHER_IMAGE,
        category="edge",
        notes="影像存在但属于其他用户，validator 必须拦截。",
    ),
    PlannerEvalCase(
        case_id="edge_invalid_imagery_wording",
        query="对刚才那张图做地物分割，但我没有提供影像 ID",
        expected_action="none",
        expected_capability=None,
        category="edge",
        notes="缺 ID 的分割请求应降级 none。",
    ),
    PlannerEvalCase(
        case_id="tool_water_mask_synonym",
        query=f"圈出影像 {PRIMARY_IMAGERY_ID} 里面的河流湖泊区域",
        expected_action="call",
        expected_capability="extract_water_mask",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="水体同义表达。",
    ),
    PlannerEvalCase(
        case_id="tool_detect_vehicle_synonym",
        query=f"找出影像 {PRIMARY_IMAGERY_ID} 中可能的车辆目标",
        expected_action="call",
        expected_capability="detect_objects",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="检测同义表达。",
    ),
    PlannerEvalCase(
        case_id="tool_document_map_ocr",
        query=f"读出影像 {PRIMARY_IMAGERY_ID} 这张扫描地图上的地名标注",
        expected_action="call",
        expected_capability="ocr_recognize",
        imagery_inventory=OWNED_IMAGE,
        category="tool_positive",
        notes="扫描地图注记 OCR。",
    ),
)


def valid_capability_names() -> set[str]:
    return set(TOOLS) | set(AGENT_CAPABILITIES)


def _bfcl_bucket(case: PlannerEvalCase) -> str:
    if case.category == "simple":
        return "simple"
    if case.category.startswith("none") or case.category.startswith("edge"):
        return "none"
    if case.category == "multiple":
        return "multiple"
    if case.category in {"parallel_web_search", "unsupported_multi_tool"}:
        return "parallel"
    if case.expected_action == "none":
        return "none"
    return case.category


def _ratio(count: int, total: int) -> float:
    return (count / total) if total else 0.0


def validate_cases(cases: tuple[PlannerEvalCase, ...] | None = None) -> None:
    if cases is None:
        cases = EVAL_CASES
    valid_names = valid_capability_names()
    seen: set[str] = set()
    errors: list[str] = []

    for case in cases:
        if case.case_id in seen:
            errors.append(f"duplicate case_id: {case.case_id}")
        seen.add(case.case_id)
        if case.expected_action == "none" and case.expected_capability is not None:
            errors.append(f"{case.case_id}: none action must not set capability")
        if case.expected_action == "call" and not case.expected_capability:
            errors.append(f"{case.case_id}: call action must set capability")
        if case.expected_capability is not None and case.expected_capability not in valid_names:
            errors.append(f"{case.case_id}: unknown capability {case.expected_capability}")
        if case.expected_arguments_subset and case.expected_action != "call":
            errors.append(f"{case.case_id}: argument subset is only valid for call cases")
        if case.min_query_count:
            if case.expected_action != "call" or case.expected_capability != "web_search":
                errors.append(f"{case.case_id}: query count expectations are only valid for web_search calls")
            if case.min_query_count < 2:
                errors.append(f"{case.case_id}: compound web_search must require at least 2 queries")
        if case.source not in {"golden", "generated"}:
            errors.append(f"{case.case_id}: invalid source {case.source}")
        if case.scoring not in {"main", "diagnostic_unsupported"}:
            errors.append(f"{case.case_id}: invalid scoring {case.scoring}")
        if case.scoring == "diagnostic_unsupported":
            if case.expected_action != "none":
                errors.append(f"{case.case_id}: diagnostic unsupported cases must expect none")
            if case.category != "unsupported_multi_tool":
                errors.append(f"{case.case_id}: diagnostic unsupported cases must use unsupported_multi_tool category")
        if case.category == "unsupported_multi_tool" and case.scoring != "diagnostic_unsupported":
            errors.append(f"{case.case_id}: unsupported_multi_tool cases must use diagnostic_unsupported scoring")

    call_capabilities = {case.expected_capability for case in cases if case.expected_action == "call"}
    missing_tools = set(TOOLS) - call_capabilities
    if missing_tools:
        errors.append(f"missing positive tool cases: {sorted(missing_tools)}")

    web_cases = [
        case
        for case in cases
        if case.expected_action == "call" and case.expected_capability == "web_search"
    ]
    if len(web_cases) < 3:
        errors.append("web_search must have at least 3 positive cases")

    none_categories = {case.case_id for case in cases if case.expected_action == "none"}
    required_none_cases = {
        "none_greeting",
        "none_ndvi_concept",
        "none_missing_imagery",
        "none_translation",
    }
    if not required_none_cases.issubset(none_categories):
        errors.append(f"missing required none cases: {sorted(required_none_cases - none_categories)}")

    generated_cases = [case for case in cases if case.source == "generated"]
    if generated_cases:
        bucket_counts: dict[str, int] = {}
        for case in generated_cases:
            bucket = _bfcl_bucket(case)
            bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        generated_total = len(generated_cases)
        none_ratio = _ratio(bucket_counts.get("none", 0), generated_total)
        if none_ratio < 0.30:
            errors.append(f"generated none ratio must be >= 30%, got {none_ratio:.3f}")
        simple_ratio = _ratio(bucket_counts.get("simple", 0), generated_total)
        multiple_ratio = _ratio(bucket_counts.get("multiple", 0), generated_total)
        parallel_ratio = _ratio(bucket_counts.get("parallel", 0), generated_total)
        if not 0.35 <= simple_ratio <= 0.45:
            errors.append(f"generated simple ratio must be near 40%, got {simple_ratio:.3f}")
        if not 0.10 <= multiple_ratio <= 0.20:
            errors.append(f"generated multiple ratio must be near 15%, got {multiple_ratio:.3f}")
        if not 0.10 <= parallel_ratio <= 0.20:
            errors.append(f"generated parallel ratio must be near 15%, got {parallel_ratio:.3f}")

    main_cases = [case for case in cases if case.scoring == "main"]
    if main_cases:
        main_none_ratio = _ratio(
            sum(1 for case in main_cases if case.expected_action == "none"),
            len(main_cases),
        )
        if main_none_ratio < 0.30:
            errors.append(f"main scoring none ratio must be >= 30%, got {main_none_ratio:.3f}")

    covered_argument_keys: set[str] = set()
    for case in cases:
        covered_argument_keys.update(case.expected_arguments_subset)
        if case.min_query_count:
            covered_argument_keys.add("queries")
    required_argument_keys = {"imagery_id", "document_id", "index_type", "mode", "dst_crs", "queries"}
    missing_argument_keys = required_argument_keys - covered_argument_keys
    if missing_argument_keys:
        errors.append(f"missing argument coverage: {sorted(missing_argument_keys)}")

    if errors:
        raise ValueError("; ".join(errors))


from tests.ai.eval.cases_generator import generate_generated_cases  # noqa: E402


GENERATED_CASES: tuple[PlannerEvalCase, ...] = generate_generated_cases()
EVAL_CASES: tuple[PlannerEvalCase, ...] = GOLDEN_CASES + GENERATED_CASES
CI_REPLAY_CASES: tuple[PlannerEvalCase, ...] = GOLDEN_CASES


validate_cases()

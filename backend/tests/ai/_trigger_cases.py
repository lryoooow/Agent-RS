from __future__ import annotations

from dataclasses import dataclass

from app.agent.router import RequestRoute
from app.agent.search.classifier import SearchIntent


@dataclass(frozen=True)
class RouteCase:
    case_id: str
    query: str
    expected: RequestRoute
    use_memory: bool = False
    use_rag: bool = False


@dataclass(frozen=True)
class SearchIntentCase:
    case_id: str
    query: str
    expected: SearchIntent
    messages: list[dict[str, str]] | None = None


@dataclass(frozen=True)
class NdviTextCase:
    case_id: str
    query: str
    wants_calculation: bool


ROUTE_CASES: tuple[RouteCase, ...] = (
    RouteCase("direct_greeting", "你好", RequestRoute.DIRECT_CHAT),
    RouteCase("direct_programming", "帮我写一个快速排序函数", RequestRoute.DIRECT_CHAT),
    RouteCase("direct_translate", "翻译这句话: hello world", RequestRoute.DIRECT_CHAT),
    RouteCase("direct_math", "帮我算一下 123 + 456", RequestRoute.DIRECT_CHAT),
    RouteCase("direct_short_ack", "好的", RequestRoute.DIRECT_CHAT, use_memory=True),
    RouteCase("pipeline_latest_news", "最近有什么遥感新闻", RequestRoute.FULL_PIPELINE),
    RouteCase("pipeline_sources", "帮我查一下这个库的官网文档来源", RequestRoute.FULL_PIPELINE),
    RouteCase("pipeline_rag_enabled", "Transformer 注意力机制怎么工作", RequestRoute.FULL_PIPELINE, use_memory=True),
    RouteCase("pipeline_doc_signal", "根据上传文档总结重点", RequestRoute.FULL_PIPELINE),
)


ROUTER_CLASSIFIER_DISAGREEMENT_CASES: tuple[str, ...] = (
    "苹果手机价格",
    "这个库的最新版本是多少",
    "2024年的遥感数据政策有哪些",
)


ROUTING_RISK_CASES: tuple[RouteCase, ...] = (
    RouteCase("risk_code_with_year", "帮我写一个2024年的排序脚本", RequestRoute.FULL_PIPELINE),
    RouteCase("risk_code_with_data", "帮我写一个数据清洗函数", RequestRoute.FULL_PIPELINE),
)


NDVI_TEXT_CASES: tuple[NdviTextCase, ...] = (
    NdviTextCase("concept_question", "什么是 NDVI", False),
    NdviTextCase("concept_explain", "解释一下 NDVI 的原理", False),
    NdviTextCase("mixed_conservative", "什么是 NDVI？顺便帮我计算一下", False),
    NdviTextCase("calculation_plain", "请计算 NDVI", True),
    NdviTextCase("calculation_alias", "帮我跑一下植被指数", True),
    NdviTextCase("calculation_imagery", "对这张遥感影像生成 NDVI", True),
)


SEARCH_INTENT_CASES: tuple[SearchIntentCase, ...] = (
    SearchIntentCase("skip_greeting", "你好", SearchIntent.SKIP),
    SearchIntentCase("skip_programming", "帮我写一个快速排序函数", SearchIntent.SKIP),
    SearchIntentCase("skip_translate", "翻译这句话: hello world", SearchIntent.SKIP),
    SearchIntentCase("skip_math", "请计算 12 * 13", SearchIntent.SKIP),
    SearchIntentCase("force_latest", "最近有什么遥感新闻", SearchIntent.FORCE),
    SearchIntentCase("force_today", "今天英伟达股价是多少", SearchIntent.FORCE),
    SearchIntentCase("force_tomorrow_weather", "明天杭州天气预报", SearchIntent.FORCE),
    SearchIntentCase("force_tomorrow_rain_level", "明天杭州有中雨吗？", SearchIntent.FORCE),
    SearchIntentCase("force_forecast_without_weather_word", "杭州明天降雨预报", SearchIntent.FORCE),
    SearchIntentCase("force_search", "帮我查一下这个库的官网", SearchIntent.FORCE),
    SearchIntentCase("force_year", "2026年 Landsat 有什么更新", SearchIntent.FORCE),
    SearchIntentCase("uncertain_general", "Transformer 注意力机制怎么工作", SearchIntent.UNCERTAIN),
    SearchIntentCase(
        "skip_followup_existing_sources",
        "那这个呢",
        SearchIntent.SKIP,
        messages=[
            {"role": "user", "content": "查一下这个新闻"},
            {"role": "assistant", "content": "根据搜索结果 [S1] 该事件已经发布。Sources: example"},
        ],
    ),
)

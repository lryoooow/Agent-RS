from __future__ import annotations

from app.agent.search.formatter import format_search_context


def test_weather_search_context_warns_against_city_forecast_inference() -> None:
    context, count = format_search_context(
        query="明天杭州有中雨吗？",
        reason="weather forecast",
        search_result={
            "results": [
                {
                    "title": "南方将有新一轮降雨",
                    "url": "https://example.com/weather",
                    "content": "6日前后南方有降雨过程。",
                }
            ]
        },
        max_chars=4000,
    )

    assert count == 1
    assert "天气类回答边界" in context
    assert "不要推断成具体城市预报" in context
    assert "不要凭常识或上下文猜测" in context


def test_non_weather_search_context_does_not_add_weather_boundary() -> None:
    context, count = format_search_context(
        query="Transformer 注意力机制",
        reason="general explanation",
        search_result={"results": []},
        max_chars=4000,
    )

    assert count == 0
    assert "天气类回答边界" not in context


def test_search_context_carries_citation_rules() -> None:
    # 问题2根因修复：原"联网搜索结果使用规则"（[S1][S2] 引用、整合提炼、冲突以搜索为准）
    # 已从 tool_policy 移到这里——只在真正联网搜索时注入，避免污染地物分割等非搜索任务。
    context, _ = format_search_context(
        query="最新遥感大模型进展",
        reason="latest research",
        search_result={
            "results": [
                {"title": "RS Foundation Models", "url": "https://example.com/rs", "content": "综述。"}
            ]
        },
        max_chars=4000,
    )

    assert "[S1] [S2]" in context
    assert "若最终回答为自然语言" in context
    assert "仅输出 JSON" in context
    assert "不要插入来源标记" in context
    assert "以搜索结果为准" in context
    assert "整合提炼" in context


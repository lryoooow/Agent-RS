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

import pytest

from app.agent.tools.web_search.agent import run_web_search
from app.agent.tools.web_search.schema import WebSearchArguments
from app.core.settings import get_settings


def reset_settings() -> None:
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_web_search_agent_calls_tavily_directly(monkeypatch):
    seen_calls = []

    async def fake_search_tavily(**kwargs):
        seen_calls.append(kwargs)
        return {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.test",
                    "content": "Result summary",
                }
            ]
        }

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    reset_settings()
    monkeypatch.setattr(
        "app.agent.tools.web_search.agent.search_tavily",
        fake_search_tavily,
    )

    result = await run_web_search(WebSearchArguments(query="latest ai news", reason="fresh info", max_results=3))

    assert seen_calls[0]["api_key"] == "test-key"
    assert seen_calls[0]["query"] == "latest ai news"
    assert seen_calls[0]["max_results"] == 3
    assert "Tool policy:" in result.tool_context
    assert "https://example.test" in result.tool_context

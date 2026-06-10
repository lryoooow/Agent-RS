import pytest

from app.agent.search.agent import run_web_search
from app.agent.search.cache import get_result_cache
from app.agent.search.schema import WebSearchArguments
from app.agent.search.tavily_client import TavilySearchError
from app.core.settings import get_settings


def reset_settings() -> None:
    get_settings.cache_clear()
    # 清掉全局结果缓存，避免上一个测试的命中污染下一个测试（ResultCache TTL 300s 跨用例存活）。
    get_result_cache().clear()


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
        "app.agent.search.agent.search_tavily",
        fake_search_tavily,
    )

    result = await run_web_search(WebSearchArguments(query="latest ai news", reason="fresh info", max_results=3))

    assert seen_calls[0]["api_key"] == "test-key"
    assert seen_calls[0]["query"] == "latest ai news"
    assert seen_calls[0]["max_results"] == 3
    assert "Tool policy:" in result.tool_context
    assert "https://example.test" in result.tool_context


def _result(title: str, url: str, content: str, score: float = 0.9) -> dict:
    return {"title": title, "url": url, "content": content, "score": score}


@pytest.mark.asyncio
async def test_web_search_runs_each_query_for_compound_question(monkeypatch):
    """复合问题的每个意图各打一次 Tavily，两类结果都进入上下文。"""
    seen_queries = []

    async def fake_search_tavily(**kwargs):
        q = kwargs["query"]
        seen_queries.append(q)
        if "天气" in q:
            return {"results": [_result("上海天气", "https://weather.test/sh", "明天上海多云转晴 26度")]}
        return {"results": [_result("自驾攻略", "https://travel.test/sh", "上海周边两天一夜路线")]}

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_WEB_SEARCH_RERANK_ENABLED", "false")
    reset_settings()
    monkeypatch.setattr("app.agent.search.agent.search_tavily", fake_search_tavily)

    args = WebSearchArguments(
        query="明天上海天气预报",
        reason="实时天气与自驾攻略",
        queries=["明天上海天气预报", "上海周边自驾游 两天一夜 攻略"],
        max_results=3,
    )
    result = await run_web_search(args)

    assert len(seen_queries) == 2
    # 两个意图的来源都进了上下文，不再只剩攻略
    assert "https://weather.test/sh" in result.tool_context
    assert "https://travel.test/sh" in result.tool_context
    assert result.result_count == 2


@pytest.mark.asyncio
async def test_web_search_dedups_urls_across_queries(monkeypatch):
    """不同检索词命中同一 URL 时只保留一次。"""

    async def fake_search_tavily(**kwargs):
        # 两条 query 都返回同一个 URL，外加各自独有的
        common = _result("共享页", "https://common.test/a", "共享内容")
        if "天气" in kwargs["query"]:
            return {"results": [common, _result("天气页", "https://w.test", "天气")]}
        return {"results": [common, _result("攻略页", "https://t.test", "攻略")]}

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_WEB_SEARCH_RERANK_ENABLED", "false")
    reset_settings()
    monkeypatch.setattr("app.agent.search.agent.search_tavily", fake_search_tavily)

    args = WebSearchArguments(
        query="天气",
        reason="r",
        queries=["天气", "攻略"],
        max_results=5,
    )
    result = await run_web_search(args)

    # 共享 URL 只出现一次：3 条而非 4 条
    assert result.result_count == 3
    # formatter 每个来源会在正文打印一行 "Source: <url>"，去重后该行只出现一次
    assert result.tool_context.count("Source: https://common.test/a") == 1


@pytest.mark.asyncio
async def test_web_search_partial_failure_keeps_successful_results(monkeypatch):
    """一条检索词失败不影响其余成功结果。"""

    async def fake_search_tavily(**kwargs):
        if "天气" in kwargs["query"]:
            raise TavilySearchError("weather endpoint down")
        return {"results": [_result("攻略页", "https://t.test", "攻略内容")]}

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_WEB_SEARCH_RERANK_ENABLED", "false")
    reset_settings()
    monkeypatch.setattr("app.agent.search.agent.search_tavily", fake_search_tavily)

    args = WebSearchArguments(query="天气", reason="r", queries=["天气", "攻略"], max_results=3)
    result = await run_web_search(args)

    assert result.error is None
    assert "https://t.test" in result.tool_context
    assert result.result_count == 1


@pytest.mark.asyncio
async def test_web_search_all_queries_fail_returns_unavailable(monkeypatch):
    """所有检索词都失败时返回不可用提示，不谎称已搜索。"""

    async def fake_search_tavily(**kwargs):
        raise TavilySearchError("all down")

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_WEB_SEARCH_RERANK_ENABLED", "false")
    reset_settings()
    monkeypatch.setattr("app.agent.search.agent.search_tavily", fake_search_tavily)

    args = WebSearchArguments(query="天气", reason="r", queries=["天气", "攻略"], max_results=3)
    result = await run_web_search(args)

    assert result.error == "all down"
    assert "temporarily unavailable" in result.tool_context


@pytest.mark.asyncio
async def test_web_search_single_query_unchanged(monkeypatch):
    """无 queries 时仅打一次 Tavily，保持原行为。"""
    seen = []

    async def fake_search_tavily(**kwargs):
        seen.append(kwargs["query"])
        return {"results": [_result("E", "https://e.test", "c")]}

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_WEB_SEARCH_RERANK_ENABLED", "false")
    reset_settings()
    monkeypatch.setattr("app.agent.search.agent.search_tavily", fake_search_tavily)

    result = await run_web_search(WebSearchArguments(query="单一问题", reason="r", max_results=3))

    assert seen == ["单一问题"]
    assert result.result_count == 1


# --- effective_queries 纯逻辑单测（不触发网络） ---

def test_effective_queries_falls_back_to_query():
    args = WebSearchArguments(query="only", reason="r")
    assert args.effective_queries() == ["only"]


def test_effective_queries_uses_queries_and_dedups_with_query():
    args = WebSearchArguments(
        query="AI News",
        reason="r",
        queries=["  ai news  ", "AI News", "stock price"],
    )
    # 大小写/空白归一后去重，query 已在 queries 中不重复追加
    assert args.effective_queries() == ["ai news", "stock price"]


def test_effective_queries_blank_queries_normalized_to_none():
    args = WebSearchArguments(query="kept", reason="r", queries=["  ", ""])
    assert args.queries is None
    assert args.effective_queries() == ["kept"]


def test_effective_queries_caps_at_max():
    args = WebSearchArguments(query="q1", reason="r", queries=["q1", "q2", "q3", "q4", "q5"])
    assert args.effective_queries() == ["q1", "q2", "q3"]
    assert args.effective_queries(max_queries=2) == ["q1", "q2"]

"""web_search 注册表 runner：成功 / 失败 / 零结果三条路径。

检索管线本身（Tavily 客户端、多检索词、过滤重排缓存）的测试在
test_web_search_agent.py；这里只测 `run_web_search_tool` 这个注册表适配层
把 ToolRunResult 翻译成"给调用方模型的指导文本"的行为。
"""

from __future__ import annotations

import pytest

from app.agent.search.schema import WebSearchArguments
from app.agent.tools.web_search.runner import run_web_search_tool, web_search_tool_available
from app.agent.types import ToolRunResult
from app.core.settings import get_settings


def _args(**overrides) -> WebSearchArguments:
    base = {"query": "Sentinel-2 数据政策", "reason": "需要最新信息"}
    base.update(overrides)
    return WebSearchArguments(**base)


@pytest.mark.asyncio
async def test_runner_success_passes_context_through(monkeypatch) -> None:
    """成功路径：检索摘要原样透传，模型拿到可直接引用的上下文。"""

    async def fake_run(args):
        assert args.max_results == get_settings().agent_web_search_max_results
        return ToolRunResult(tool_context="检索结果：……", result_count=3, query=args.query)

    monkeypatch.setattr("app.agent.tools.web_search.runner.run_web_search", fake_run)
    result = await run_web_search_tool(_args())
    assert result.error is None
    assert result.tool_context == "检索结果：……"
    assert result.result_count == 3


@pytest.mark.asyncio
async def test_runner_failure_names_the_error_and_forbids_fabrication(monkeypatch) -> None:
    async def boom(_args):
        raise RuntimeError("Tavily 超时")

    monkeypatch.setattr("app.agent.tools.web_search.runner.run_web_search", boom)
    result = await run_web_search_tool(_args())
    assert result.error is not None
    assert "检索失败" in result.tool_context
    assert "不要编造" in result.tool_context


@pytest.mark.asyncio
async def test_runner_empty_results_invite_retry(monkeypatch) -> None:
    """零结果不是错误：换词重试的指导进 tool_context，error 保持空。"""

    async def empty(_args):
        return ToolRunResult(tool_context="", result_count=0)

    monkeypatch.setattr("app.agent.tools.web_search.runner.run_web_search", empty)
    result = await run_web_search_tool(_args())
    assert result.error is None
    assert "换一组检索词" in result.tool_context


def test_availability_follows_tavily_config(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    try:
        assert not web_search_tool_available()
    finally:
        get_settings.cache_clear()

    monkeypatch.setenv("TAVILY_API_KEY", "some-key")
    get_settings.cache_clear()
    try:
        assert web_search_tool_available()
    finally:
        get_settings.cache_clear()

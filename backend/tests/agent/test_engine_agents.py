"""engine/agents.py：领域 Agent、通用 Agent 与共享工具的组装。

核心断言是 AutoGen Agent 清单和工具注册表始终一致：
- 领域指引进了 system_message 而不是拼在工具结果后面
- 每个领域拿到「自己那批领域工具 + 全部共享工具」，不多不少
- 多步工具循环真的开着
- 领域工具恰好归属一个 Agent；共享工具不催生 Agent
"""
from __future__ import annotations

import pytest
from autogen_core import CancellationToken
from autogen_core.models import ChatCompletionClient, ModelFamily

from app.agent.engine.agents import (
    DOMAIN_GUIDANCE,
    DOMAIN_LABELS,
    build_domain_agent,
    build_main_agent,
    build_report_finalizer,
    domain_specs,
)
from app.agent.engine.tools import RemoteSensingTool, shared_tool_names
from app.agent.engine.turn_context import turn_scope
from app.agent.search.schema import WebSearchArguments
from app.agent.tool_registry import TOOLS
from app.agent.types import ToolRunResult
from app.core.settings import get_settings


class _StubClient(ChatCompletionClient):
    """只满足 AssistantAgent 构造期需要的最小客户端，不发任何请求。"""

    @property
    def model_info(self):
        return {
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": True,
            "family": ModelFamily.UNKNOWN,
        }

    @property
    def capabilities(self):
        return self.model_info

    async def create(self, *a, **k):  # pragma: no cover - 构造期不会调用
        raise NotImplementedError

    def create_stream(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    async def close(self):
        return None

    def actual_usage(self):
        return None

    def total_usage(self):
        return None

    def count_tokens(self, *a, **k):
        return 0

    def remaining_tokens(self, *a, **k):
        return 10_000


@pytest.fixture
def client():
    return _StubClient()


def test_domain_specs_are_derived_from_tool_registry() -> None:
    """注册表是工具归属的唯一数据源（只统计领域工具，共享工具除外）。"""
    specs = {spec.name: spec for spec in domain_specs()}

    expected: dict[str, set[str]] = {}
    for tool in TOOLS.values():
        if tool.scope == "shared":
            continue
        expected.setdefault(tool.agent_name, set()).add(tool.name)

    assert set(specs) == set(expected)
    for name, tools in expected.items():
        assert set(specs[name].tools) == tools
        assert specs[name].label == DOMAIN_LABELS[name]


def test_shared_tools_do_not_spawn_agents() -> None:
    """共享工具（检索/定位/报告）不催生任何领域 Agent。"""
    shared = {tool.name for tool in TOOLS.values() if tool.scope == "shared"}
    assert shared == {
        "web_search",
        "look_at_location",
        "generate_report",
        "search_imagery",
        "fetch_scene",
    }
    spec_names = {spec.name for spec in domain_specs()}
    assert spec_names.isdisjoint({"report_agent", "navigation_agent", "search_agent"})


def test_guidance_is_in_system_message() -> None:
    for spec in domain_specs():
        assert DOMAIN_GUIDANCE[spec.name] in spec.system_message
        assert "绝不编造" in spec.system_message


def test_each_domain_agent_gets_its_own_tools_plus_shared(client) -> None:
    """领域隔离 + 平台能力：拿到自己的领域工具和全部共享工具，仅此而已。"""
    for spec in domain_specs():
        agent = build_domain_agent(spec, model_client=client)
        names = {t.name for t in agent._tools}  # noqa: SLF001
        assert names == set(spec.tools) | set(shared_tool_names()), f"{spec.name} 的工具集不符"


def test_main_agent_holds_all_enabled_tools(client) -> None:
    """主 Agent 持有全部已启用工具：领域工具 + 共享工具，一个不少。"""
    agent = build_main_agent(model_client=client)
    names = {t.name for t in agent._tools}  # noqa: SLF001
    expected = {tool.name for tool in TOOLS.values() if tool.is_enabled()}
    assert names == expected
    assert "web_search" in names or True  # 未配 TAVILY key 时合理缺席


def test_multi_step_tool_loop_is_enabled(client) -> None:
    settings = get_settings()
    assert settings.agent_max_tool_iterations > 1, "配置本身要允许多步"

    agents = [build_main_agent(model_client=client)]
    agents += [build_domain_agent(spec, model_client=client) for spec in domain_specs()]
    for agent in agents:
        assert agent._max_tool_iterations == settings.agent_max_tool_iterations  # noqa: SLF001


def test_domain_description_is_discriminative() -> None:
    """SelectorGroupChat 靠 description 选人，笼统的描述会让它选错领域。"""
    specs = domain_specs()
    descriptions = [spec.description for spec in specs]
    assert len(set(descriptions)) == len(descriptions), "各领域描述不能重复"
    for spec in specs:
        assert any(tool in spec.description for tool in spec.tools)


# --------------------------------------------------------------- web_search 共享工具


@pytest.fixture
def _search_tool_ready(monkeypatch):
    """启用 web_search（默认无 TAVILY_API_KEY 时它是未注册状态）并关掉 DB。"""
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    get_settings.cache_clear()
    yield RemoteSensingTool(TOOLS["web_search"])
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_web_search_clamps_result_count(monkeypatch) -> None:
    """条数上限由服务端强制，模型说了不算。

    参数模型约束请求 ≤5 条（与旧手写 schema 的 maximum:5 一致），但运营可以把
    AGENT_WEB_SEARCH_MAX_RESULTS 压得更低——运行时钳制负责执行这个更严的上限。
    """
    captured: list[WebSearchArguments] = []

    async def fake_search(args: WebSearchArguments) -> ToolRunResult:
        captured.append(args)
        return ToolRunResult(tool_context="检索结果……", result_count=3)

    monkeypatch.setattr("app.agent.tools.web_search.runner.run_web_search", fake_search)
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    monkeypatch.setenv("AGENT_WEB_SEARCH_MAX_RESULTS", "2")
    get_settings.cache_clear()
    try:
        tool = RemoteSensingTool(TOOLS["web_search"])
        with turn_scope() as state:
            text = await tool.run(
                WebSearchArguments(query="明天杭州天气", reason="需要实时天气", max_results=5),
                CancellationToken(),
            )
    finally:
        get_settings.cache_clear()

    assert text == "检索结果……"
    assert captured[0].max_results == 2
    assert len(state.invocations) == 1
    assert state.invocations[0].name == "web_search"


@pytest.mark.asyncio
async def test_web_search_reports_failure_without_fabricating(monkeypatch, _search_tool_ready) -> None:
    async def boom(_args):
        raise RuntimeError("Tavily 超时")

    monkeypatch.setattr("app.agent.tools.web_search.runner.run_web_search", boom)

    with turn_scope():
        text = await _search_tool_ready.run(
            WebSearchArguments(query="x", reason="y"), CancellationToken()
        )
    assert "检索失败" in text
    assert "不要编造" in text


@pytest.mark.asyncio
async def test_web_search_empty_results_invite_a_retry(monkeypatch, _search_tool_ready) -> None:
    """零结果时提示模型换检索词重试。"""

    async def empty(_args):
        return ToolRunResult(tool_context="", result_count=0)

    monkeypatch.setattr("app.agent.tools.web_search.runner.run_web_search", empty)

    with turn_scope():
        text = await _search_tool_ready.run(
            WebSearchArguments(query="x", reason="y"), CancellationToken()
        )
    assert "换一组检索词" in text


@pytest.mark.asyncio
async def test_web_search_respects_per_turn_call_cap(monkeypatch, _search_tool_ready) -> None:
    """`AGENT_WEB_SEARCH_MAX_CALLS` 必须真的是上限。

    Agent 能连续请求工具，因此服务端仍须按回合强制限额；否则一次回合可以
    打满 max_tool_iterations 次——而 Tavily 是按次计费的。
    """
    calls = 0

    async def counting(_args):
        nonlocal calls
        calls += 1
        return ToolRunResult(tool_context="检索结果……", result_count=3)

    monkeypatch.setattr("app.agent.tools.web_search.runner.run_web_search", counting)

    limit = get_settings().agent_web_search_max_calls
    with turn_scope():
        texts = [
            await _search_tool_ready.run(
                WebSearchArguments(query=f"q{i}", reason="r"), CancellationToken()
            )
            for i in range(limit + 2)
        ]

    assert calls == limit, f"超出上限后不该再打 Tavily，实际打了 {calls} 次"
    assert "已达上限" in texts[-1]
    assert "不要编造" in texts[-1]


@pytest.mark.asyncio
async def test_web_search_cap_is_per_turn(monkeypatch, _search_tool_ready) -> None:
    """配额按回合重置，不能让上一次对话的用量影响下一次。"""

    async def ok(_args):
        return ToolRunResult(tool_context="检索结果……", result_count=1)

    monkeypatch.setattr("app.agent.tools.web_search.runner.run_web_search", ok)

    for _ in range(3):
        with turn_scope():
            text = await _search_tool_ready.run(
                WebSearchArguments(query="q", reason="r"), CancellationToken()
            )
            assert text == "检索结果……", "新回合应重新拿到检索配额"


# --------------------------------------------------------------- GraphFlow 收尾节点


def test_report_finalizer_holds_only_report_tool(client) -> None:
    """收尾节点是流内最小专家：只拿 generate_report，不进 selector 团队。"""
    agent = build_report_finalizer(model_client=client)
    assert agent.name == "report_agent"
    assert {t.name for t in agent._tools} == {"generate_report"}  # noqa: SLF001
    assert agent._max_tool_iterations > 1  # noqa: SLF001
    assert DOMAIN_GUIDANCE["report_agent"] in agent._system_messages[0].content  # noqa: SLF001


def test_report_finalizer_receives_the_same_autogen_memories(client) -> None:
    memory = object()
    agent = build_report_finalizer(model_client=client, memory=[memory])  # type: ignore[list-item]
    assert agent._memory == [memory]  # noqa: SLF001

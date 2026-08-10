"""engine/agents.py + engine/search.py：领域 Agent 与搜索 Agent。

核心断言是「这次真的把假 Agent 变成了真 Agent」：
- 领域指引进了 system_message 而不是拼在工具结果后面
- 每个领域只拿到自己那批工具
- 多步工具循环真的开着（legacy 硬编码为 1）
- 领域划分与 legacy 的三张表严格一致，迁移不顺手改产品决策
"""
from __future__ import annotations

import pytest
from autogen_core import CancellationToken
from autogen_core.models import ChatCompletionClient, ModelFamily

from app.agent.domain_agents import DOMAIN_GUIDANCE, DOMAIN_LABELS, TOOL_DOMAIN
from app.agent.engine.agents import build_domain_agent, build_domain_agents, domain_specs
from app.agent.engine.search import WebSearchTool, build_search_agent
from app.agent.engine.turn_context import turn_scope
from app.agent.search.schema import WebSearchArguments
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


def test_domain_specs_match_legacy_tables() -> None:
    """领域划分必须与 legacy 完全一致——迁移不该顺手改产品决策。"""
    specs = {spec.name: spec for spec in domain_specs()}

    expected: dict[str, set[str]] = {}
    for tool, domain in TOOL_DOMAIN.items():
        expected.setdefault(domain, set()).add(tool)

    assert set(specs) == set(expected)
    for name, tools in expected.items():
        assert set(specs[name].tools) == tools
        assert specs[name].label == DOMAIN_LABELS[name]


def test_guidance_becomes_system_message_not_appended_text() -> None:
    """legacy 把领域指引拼在工具结果尾部；现在它必须是 Agent 的 system_message。

    差别不是形式：拼在结果后面时模型只是"读到一段话"，
    作为 system_message 时它才是这个 Agent 的行为准则，能影响它要不要再调一次工具。
    """
    for spec in domain_specs():
        assert DOMAIN_GUIDANCE[spec.name] in spec.system_message
        assert "绝不编造" in spec.system_message


def test_each_domain_agent_only_gets_its_own_tools(client) -> None:
    """领域隔离：指数分析的 Agent 不该拿得到目标检测工具。"""
    for spec in domain_specs():
        agent = build_domain_agent(spec, model_client=client)
        names = {t.name for t in agent._tools}  # noqa: SLF001
        assert names == set(spec.tools), f"{spec.name} 的工具集不符"


def test_multi_step_tool_loop_is_enabled(client) -> None:
    """这一条就是整个迁移的目的：legacy 硬编码 max_tool_calls=1。"""
    settings = get_settings()
    assert settings.agent_max_tool_iterations > 1, "配置本身要允许多步"

    for agent in build_domain_agents(model_client=client):
        assert agent._max_tool_iterations == settings.agent_max_tool_iterations  # noqa: SLF001


def test_domain_description_is_discriminative() -> None:
    """SelectorGroupChat 靠 description 选人，笼统的描述会让它选错领域。"""
    specs = domain_specs()
    descriptions = [spec.description for spec in specs]
    assert len(set(descriptions)) == len(descriptions), "各领域描述不能重复"
    for spec in specs:
        assert any(tool in spec.description for tool in spec.tools)


# --------------------------------------------------------------- 搜索 Agent


@pytest.mark.asyncio
async def test_search_tool_clamps_result_count(monkeypatch) -> None:
    """条数上限由服务端强制，模型说了不算——否则它能要 100 条把上下文撑爆。"""
    captured: list[WebSearchArguments] = []

    async def fake_search(args: WebSearchArguments) -> ToolRunResult:
        captured.append(args)
        return ToolRunResult(tool_context="检索结果……", result_count=3)

    monkeypatch.setattr("app.agent.engine.search.run_web_search", fake_search)

    with turn_scope() as state:
        text = await WebSearchTool().run(
            WebSearchArguments(query="明天杭州天气", reason="需要实时天气", max_results=999),
            CancellationToken(),
        )

    assert text == "检索结果……"
    limit = get_settings().agent_web_search_max_results
    assert captured[0].max_results == limit
    assert len(state.invocations) == 1


@pytest.mark.asyncio
async def test_search_tool_reports_failure_without_fabricating(monkeypatch) -> None:
    async def boom(_args):
        raise RuntimeError("Tavily 超时")

    monkeypatch.setattr("app.agent.engine.search.run_web_search", boom)

    with turn_scope():
        text = await WebSearchTool().run(
            WebSearchArguments(query="x", reason="y"), CancellationToken()
        )
    assert "检索失败" in text
    assert "不要编造" in text


@pytest.mark.asyncio
async def test_empty_results_invite_a_retry(monkeypatch) -> None:
    """零结果时要提示模型换检索词重试——这正是 legacy 做不到的自主性。"""

    async def empty(_args):
        return ToolRunResult(tool_context="", result_count=0)

    monkeypatch.setattr("app.agent.engine.search.run_web_search", empty)

    with turn_scope():
        text = await WebSearchTool().run(
            WebSearchArguments(query="x", reason="y"), CancellationToken()
        )
    assert "换一组检索词" in text


def test_search_agent_can_loop(client) -> None:
    """多轮检索能力：查一次不够要能再查。"""
    agent = build_search_agent(model_client=client)
    assert agent._max_tool_iterations > 1  # noqa: SLF001
    assert {t.name for t in agent._tools} == {"web_search"}  # noqa: SLF001


@pytest.mark.asyncio
async def test_web_search_respects_per_turn_call_cap(monkeypatch) -> None:
    """`AGENT_WEB_SEARCH_MAX_CALLS` 必须真的是上限。

    legacy 靠 `routing.max_tool_calls=1` 间接卡住了它；AutoGen 下 Agent 能连续要工具，
    不在工具里拦就等于这个设置只剩「开/关」的作用，一个回合能打满 max_tool_iterations 次
    ——而 Tavily 是按次计费的。
    """
    calls = 0

    async def counting(_args):
        nonlocal calls
        calls += 1
        return ToolRunResult(tool_context="检索结果……", result_count=3)

    monkeypatch.setattr("app.agent.engine.search.run_web_search", counting)

    limit = get_settings().agent_web_search_max_calls
    tool = WebSearchTool()
    with turn_scope():
        texts = [
            await tool.run(WebSearchArguments(query=f"q{i}", reason="r"), CancellationToken())
            for i in range(limit + 2)
        ]

    assert calls == limit, f"超出上限后不该再打 Tavily，实际打了 {calls} 次"
    assert "已达上限" in texts[-1]
    assert "不要编造" in texts[-1]


@pytest.mark.asyncio
async def test_web_search_cap_is_per_turn(monkeypatch) -> None:
    """配额按回合重置，不能让上一次对话的用量影响下一次。"""

    async def ok(_args):
        return ToolRunResult(tool_context="检索结果……", result_count=1)

    monkeypatch.setattr("app.agent.engine.search.run_web_search", ok)

    tool = WebSearchTool()
    for _ in range(3):
        with turn_scope():
            text = await tool.run(
                WebSearchArguments(query="q", reason="r"), CancellationToken()
            )
            assert text == "检索结果……", "新回合应重新拿到检索配额"

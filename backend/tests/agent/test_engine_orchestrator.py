"""engine/orchestrator.py：路由互斥、正文净化与结果抽取。

Phase 4 移除了 SelectorGroupChat 与 [DONE]/[HANDOFF] 交棒协议后，这里守的是：

- 路由互斥：graph → build_flow，main → build_main_agent，互相不得越界；
- 流式净化：`<think>` 推理块与叙述式推理旁白在任何分片粒度下都不进用户正文；
- 结果抽取：GraphFlow 各节点的结论都留在落库正文里，思考块剥干净。
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from autogen_agentchat.messages import TextMessage
from autogen_agentchat.conditions import ExternalTermination

from app.agent.engine.orchestrator import (
    AnswerStreamSanitizer,
    _clean_final_text,
    _to_result,
    build_orchestration,
)
from app.agent.engine.input import TurnInput
from app.agent.engine.router import RouteResult
from app.agent.engine.orchestrator import Orchestration
from app.agent.engine.turn_context import TurnToolState


def _text(content: str, source: str = "spectral_agent") -> TextMessage:
    return TextMessage(content=content, source=source)


# --------------------------------------------------------------- 路由互斥


@pytest.mark.asyncio
async def test_graph_route_builds_graphflow_not_main_agent(monkeypatch) -> None:
    client = type("Client", (), {"close": AsyncMock()})()
    team = object()

    async def choose(*_args, **_kwargs):
        return RouteResult(
            strategy="graph",
            flow_name="detect_report",
            reason="complete standard flow",
        )

    captured = {}

    def build(name, **kwargs):
        captured.update(name=name, **kwargs)
        return team

    monkeypatch.setattr("app.agent.engine.orchestrator.choose_route", choose)
    monkeypatch.setattr("app.agent.engine.orchestrator.build_model_client", lambda *_: client)
    monkeypatch.setattr("app.agent.engine.orchestrator.build_flow", build)
    monkeypatch.setattr(
        "app.agent.engine.orchestrator.build_main_agent",
        lambda **_: pytest.fail("GraphFlow 路由不得构造主 Agent"),
    )

    orchestration = await build_orchestration(
        turn=TurnInput("检测并生成报告", ()),
        user_id=None,
        use_rag=False,
        use_memory=False,
        config=object(),  # type: ignore[arg-type]
    )

    assert orchestration.team is team
    assert orchestration.route.strategy == "graph"
    assert orchestration.stop is not None, "GraphFlow 必须拿到外部终止开关"
    assert captured["name"] == "detect_report"
    assert captured["context_factory"] is not None


@pytest.mark.asyncio
async def test_main_route_builds_main_agent_not_flow(monkeypatch) -> None:
    client = type("Client", (), {"close": AsyncMock()})()
    agent = object()

    async def choose(*_args, **_kwargs):
        return RouteResult(strategy="main", flow_name=None, reason="free-form")

    monkeypatch.setattr("app.agent.engine.orchestrator.choose_route", choose)
    monkeypatch.setattr("app.agent.engine.orchestrator.build_model_client", lambda *_: client)
    monkeypatch.setattr(
        "app.agent.engine.orchestrator.build_flow",
        lambda *_args, **_kwargs: pytest.fail("main 路由不得构造 GraphFlow"),
    )
    monkeypatch.setattr("app.agent.engine.orchestrator.build_main_agent", lambda **_: agent)

    orchestration = await build_orchestration(
        turn=TurnInput("自由任务", ()),
        user_id=None,
        use_rag=False,
        use_memory=False,
        config=object(),  # type: ignore[arg-type]
    )

    assert orchestration.team is agent
    assert orchestration.route.strategy == "main"
    assert orchestration.stop is None, "主 Agent 没有可停的后续步骤"


def test_shared_web_search_tool_gated_by_tavily_key(monkeypatch) -> None:
    """检索工具的注册门控：未配 TAVILY_API_KEY（或配额为零）时工具不可用。"""
    from app.agent.tool_registry import get_tool
    from app.core.settings import get_settings

    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    try:
        tool = get_tool("web_search")
        assert tool is not None
        assert not tool.is_enabled()
    finally:
        get_settings.cache_clear()


# ------------------------------------------------- 模型思考块不能进用户正文


def _run_sanitizer(text: str, chunk_size: int) -> str:
    """按给定分片大小把文本喂给净化器，返回用户实际看到的正文。"""
    sanitizer = AnswerStreamSanitizer()
    out = [sanitizer.feed(text[i : i + chunk_size]) for i in range(0, len(text), chunk_size)]
    out.append(sanitizer.flush())
    return "".join(out)


@pytest.mark.parametrize("chunk_size", [1, 4, 8, 64])
def test_sanitizer_keeps_plain_answer_intact(chunk_size: int) -> None:
    """没有思考块的普通回答必须一字不改地流出去。"""
    raw = "NDVI 全称是归一化植被指数，取值范围 -1 到 1。"
    assert _run_sanitizer(raw, chunk_size) == raw


def test_clean_final_text_removes_think_block() -> None:
    """实测漏出：整段 `<think>` 推理直接显示给了用户。"""
    raw = (
        "<think>用户只是打了个招呼，没有提出任何遥感任务需求。"
        "根据铁律第 4 条，直接回答即可，不需要调用工具。</think>"
        "你好！有什么可以帮你的吗？"
    )
    assert _clean_final_text(raw) == "你好！有什么可以帮你的吗？"


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 8, 13, 200])
def test_sanitizer_never_leaks_think_at_any_chunk_boundary(chunk_size: int) -> None:
    """`<think>` 会被切成 `<th` + `ink>`，必须逐粒度穷举。"""
    raw = (
        "<think>用户想做目标检测，但没给影像 ID，我需要问他要。</think>"
        "好的！请把影像 ID 发给我。"
    )
    assert _run_sanitizer(raw, chunk_size) == "好的！请把影像 ID 发给我。"


def test_sanitizer_think_state_resets_per_message() -> None:
    """上一条消息以未闭合的 `<think>` 结束，不能把下一条的正文整段吃掉。"""
    sanitizer = AnswerStreamSanitizer()
    sanitizer.feed("<think>这条被截断了")
    sanitizer.flush()
    assert sanitizer.feed("第二步完成。") == "第二步完成。"


@pytest.mark.parametrize(
    "wrapped",
    [
        "<THINK>绝密推理</THINK>公开内容",
        "<thinking>绝密推理</thinking>公开内容",
        "<analysis>绝密推理</analysis>公开内容",
        "<reasoning>绝密推理</reasoning>公开内容",
    ],
)
def test_sanitizer_discards_reasoning_aliases_and_case(wrapped: str) -> None:
    sanitizer = AnswerStreamSanitizer()
    output = "".join(sanitizer.feed(char) for char in wrapped) + sanitizer.flush()
    assert output == "公开内容"
    assert "绝密推理" not in output


@pytest.mark.parametrize("chunk_size", [1, 2, 5, 13, 200])
def test_sanitizer_discards_narrated_reasoning_in_content_channel(chunk_size: int) -> None:
    """模型偶尔不走 reasoning_content，而把显式过程旁白误写进正文通道。"""
    raw = (
        "思考过程：\n分析用户需求；检查系统提示词；决定调用工具。\n"
        "思考过程结束\n\n这是可展示的正式回答。"
    )
    output = _run_sanitizer(raw, chunk_size)
    assert output == "这是可展示的正式回答。"
    assert "系统提示词" not in output
    assert "分析用户需求" not in output


def test_sanitizer_does_not_mistake_normal_discussion_for_reasoning() -> None:
    raw = "思考过程是否应该对用户展示？通常不应该展示原始推理。"
    assert _run_sanitizer(raw, 1) == raw


def test_unclosed_narrated_reasoning_fails_closed_without_unbounded_output() -> None:
    raw = "思考过程：\n" + ("绝密推理" * 10_000)
    assert _run_sanitizer(raw, 7) == ""


# ------------------------------------------------- 结果抽取


def test_to_result_keeps_every_step_and_strips_think() -> None:
    """GraphFlow 各节点结论都保留、思考块剥干净、用户消息不算正文。

    只留最后一条节点消息时，用户在流式过程中看到了"NDVI 均值 0.42"，
    刷新页面却消失——前后不一致。
    """
    from autogen_agentchat.base import TaskResult
    from unittest.mock import MagicMock

    result = TaskResult(
        messages=[
            _text("先算 NDVI，再出报告", source="user"),
            _text("<think>调用工具计算</think>已完成 NDVI 计算，均值 0.42。"),
            _text("报告已生成。", "report_agent"),
        ],
        stop_reason="done",
    )
    client = MagicMock()
    client.total_usage.return_value.prompt_tokens = 0
    client.total_usage.return_value.completion_tokens = 0
    orchestration = Orchestration(
        team=MagicMock(),
        stop=None,
        model_client=client,
        route=RouteResult(strategy="main", flow_name=None, reason="test"),
    )
    content = _to_result(result, TurnToolState(), orchestration).content
    assert content == "已完成 NDVI 计算，均值 0.42。\n\n报告已生成。"
    assert "<think>" not in content

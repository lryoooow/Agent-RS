"""engine/service.py：流式正文的对外契约（Phase 4 单主 Agent 架构）。

跑的是**真** AssistantAgent（只把模型客户端换成脚本），因为这里要验的几件事
都只在真实消息流里才会暴露：分片怎么切、工具循环的事件顺序、断连后的收尾。
用手搓的假消息序列测不出来。

不变量：

1. `<think>` 推理与叙述式旁白不进流式正文与落库正文；
2. 普通回答一字不改地流出去，流式看到的与落库一致（否则刷新页面内容会变）；
3. 工具循环里，工具 trace 事件按序发出、最终答复正确、used_tool 为真；
4. 前端断连后收尾不泄漏任务，模型客户端每回合关闭。

（此前 SelectorGroupChat 的 [DONE]/[HANDOFF] 脚手架剥离用例随交棒协议一起
删除——单主 Agent 不再输出任何控制行，没有可剥离的脚手架。）
"""
from __future__ import annotations

import json

import pytest
from autogen_core import FunctionCall
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    ModelFamily,
    RequestUsage,
)

import app.agent.engine.orchestrator as orchestrator
from app.agent.engine.router import RouteResult
from app.agent.engine.service import stream_turn_events
from app.agent.types import ToolRunResult
from app.schemas.chat import ChatMessage, ChatRequest


class _ScriptedClient(ChatCompletionClient):
    """主 Agent 路径全部走 create_stream；每个元素是一次模型调用的完整回复。

    回复要么是纯文本（最终答复），要么是 FunctionCall 列表（触发工具循环）。
    分片大小刻意取 8，好让 `<think>` 标签被切断在分片中间——这正是
    推理内容漏进用户正文的真实成因。

    create() 在这条路径上不该被调用（路由已被 monkeypatch、无 selector），
    一旦调用立即失败，防止悄悄引入隐藏的模型往返。
    """

    def __init__(self, replies: list, chunk: int = 8) -> None:
        self._replies = list(replies)
        self._chunk = chunk
        self.stream_calls = 0

    @property
    def model_info(self):
        return {
            "vision": False,
            "function_calling": True,
            "json_output": True,
            "structured_output": True,
            "family": ModelFamily.UNKNOWN,
            "multiple_system_messages": True,
        }

    @property
    def capabilities(self):
        return self.model_info

    async def create(self, messages, **kwargs):  # pragma: no cover - 契约：不该走到
        raise AssertionError("主 Agent 路径不应出现非流式模型调用")

    async def create_stream(self, messages, **kwargs):
        self.stream_calls += 1
        reply = self._replies.pop(0) if self._replies else "好的。"
        if isinstance(reply, list):
            # AutoGen 契约：FunctionCall 列表放在 content 里（content 为 str 时
            # 会被当作最终文本直接返回，工具调用被忽略）。
            yield CreateResult(
                finish_reason="function_calls",
                content=reply,
                usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
                cached=False,
            )
            return
        for i in range(0, len(reply), self._chunk):
            yield reply[i : i + self._chunk]
        yield CreateResult(
            finish_reason="stop",
            content=reply,
            usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
            cached=False,
        )

    async def close(self):
        return None

    def actual_usage(self):
        return RequestUsage(prompt_tokens=0, completion_tokens=0)

    def total_usage(self):
        return RequestUsage(prompt_tokens=0, completion_tokens=0)

    def count_tokens(self, *a, **k):
        return 0

    def remaining_tokens(self, *a, **k):
        return 10_000


def _route_main(monkeypatch, client) -> None:
    monkeypatch.setattr(orchestrator, "build_model_client", lambda *a, **k: client)

    async def _main(*_args, **_kwargs):
        return RouteResult(strategy="main", flow_name=None, reason="test")

    monkeypatch.setattr(orchestrator, "choose_route", _main)


async def _run(monkeypatch, replies, *, query: str = "这张图的影像质量怎么样"):
    client = _ScriptedClient(replies)
    _route_main(monkeypatch, client)

    deltas: list[str] = []
    statuses: list[str] = []
    final = None
    async for kind, payload in stream_turn_events(
        request=ChatRequest(
            messages=[ChatMessage(role="user", content=query)],
            use_rag=False,
            use_memory=False,
        ),
        user_id=None,
    ):
        if kind == "delta":
            deltas.append(payload)
        elif kind == "status":
            statuses.append(payload.stage)
        elif kind == "thinking":
            pytest.fail("engine 不得再产生原始 thinking 事件")
        elif kind == "final":
            final = payload
    assert final is not None, "编排必须产出最终结果"
    return "".join(deltas), final, statuses, client


# --------------------------------------------------------------- 正文契约


@pytest.mark.asyncio
async def test_raw_reasoning_never_reaches_stream_or_saved_answer(monkeypatch) -> None:
    """供应商 reasoning_content 经 AutoGen 包成标签后必须在 engine 边界永久丢弃。"""
    secret = "SYSTEM_PROMPT_AND_PRIVATE_CHAIN_SECRET"
    reply = f"<think>{secret}</think>公开答案。"

    streamed, final, _, _ = await _run(monkeypatch, [reply], query="你好")

    assert streamed == "公开答案。"
    assert final.content == "公开答案。"
    assert secret not in streamed
    assert secret not in final.content


@pytest.mark.asyncio
async def test_single_agent_answer_is_unchanged_and_streamed_equals_saved(monkeypatch) -> None:
    """最常见的情况：主 Agent 直接作答，正文原样流出去，且流式与落库一致。"""
    plain = "NDVI 全称是归一化植被指数，取值范围 -1 到 1。"
    streamed, final, _, _ = await _run(monkeypatch, [plain], query="NDVI 是什么")

    assert streamed == plain
    assert final.content == plain
    assert final.used_tool is False


# --------------------------------------------------------------- 工具循环


@pytest.mark.asyncio
async def test_tool_loop_emits_trace_events_and_final_answer(monkeypatch) -> None:
    """工具循环：先要工具、执行、再给最终答复；trace 事件按序、正文正确。

    工具执行被 monkeypatch 成罐头结果——这里测的是**编排契约**（事件顺序、
    流式/落库一致、used_tool），不是 raster_inspect 本身。
    """
    tool_call = [
        FunctionCall(
            id="call_1",
            name="raster_inspect",
            arguments=json.dumps(
                {"imagery_id": "94e758f38ede", "reason": "用户要求检查影像"},
                ensure_ascii=False,
            ),
        )
    ]
    answer = "影像共 4 个波段，质量良好。"

    async def fake_prepare(tool_name, arguments, *, user_id):
        return object()  # 非 PrepareRejected 即视为通过（真实校验另有专测）

    async def fake_run(_prepared) -> ToolRunResult:
        return ToolRunResult(tool_context="影像质检：4 波段，CRS EPSG:32650，无 nodata。")

    monkeypatch.setattr("app.agent.engine.tools.prepare_tool_call", fake_prepare)
    monkeypatch.setattr("app.agent.engine.tools.run_prepared_tool", fake_run)

    streamed, final, statuses, client = await _run(monkeypatch, [tool_call, answer])

    assert streamed == answer
    assert final.content == answer
    assert final.used_tool is True
    assert client.stream_calls == 2, "工具调用后必须再有一次模型调用产出答复"
    # trace 契约：工具请求 → 执行开始 → 执行完成（事件桥翻译顺序）。
    assert "tool_requested" in statuses
    assert "tool_execution_started" in statuses
    assert "tool_execution_completed" in statuses


# ------------------------------------------------------------------ 断连收尾


@pytest.mark.asyncio
async def test_disconnect_drains_without_leaking_tasks(monkeypatch) -> None:
    """前端断连后收尾必须干净：不留永不结束的任务。

    主 Agent 路径没有"后续步骤"可停；断连后由 `_abandon` 在后台排空在飞
    调用并关闭模型客户端。
    """
    import asyncio

    client = _ScriptedClient(["答复第一部分。\n答复第二部分。"])
    _route_main(monkeypatch, client)

    before = {id(t) for t in asyncio.all_tasks()}

    gen = stream_turn_events(
        request=ChatRequest(
            messages=[ChatMessage(role="user", content="随便聊聊")],
            use_rag=False,
            use_memory=False,
        ),
        user_id=None,
    )
    seen = 0
    async for _kind, _payload in gen:
        seen += 1
        if seen >= 2:
            break                                  # 模拟前端断连
    await gen.aclose()

    # 给后台排空任务跑完的机会
    for _ in range(50):
        await asyncio.sleep(0.02)
        if not [t for t in asyncio.all_tasks() if id(t) not in before and not t.done()]:
            break

    leaked = [
        t
        for t in asyncio.all_tasks()
        if id(t) not in before and t is not asyncio.current_task() and not t.done()
    ]
    assert not leaked, f"断连不能留下永不结束的任务：{[t.get_name() for t in leaked]}"


@pytest.mark.asyncio
async def test_model_client_is_closed_after_a_normal_turn(monkeypatch) -> None:
    """模型客户端每回合新建，就必须每回合关闭——它自带一个 httpx 连接池，
    不关的话每个聊天请求泄漏一个，最后耗尽文件描述符。"""
    client = _ScriptedClient(["答复。"])
    closed: list[bool] = []

    async def _close():
        closed.append(True)

    client.close = _close  # type: ignore[method-assign]
    _route_main(monkeypatch, client)

    async for _kind, _payload in stream_turn_events(
        request=ChatRequest(
            messages=[ChatMessage(role="user", content="NDVI 是什么")],
            use_rag=False,
            use_memory=False,
        ),
        user_id=None,
    ):
        pass

    assert closed, "回合结束必须关闭模型客户端"


# ================================================================ 非流式路径


@pytest.mark.asyncio
async def test_complete_turn_returns_correct_output_shape(monkeypatch) -> None:
    """非流式 complete_turn 产出的 AutogenTurnOutput 字段形状正确。

    此前只有流式路径通过 stream_turn_events 间接被测，
    非流式路径（run_turn → agent.run）完全裸奔。
    """
    from app.agent.engine.service import complete_turn

    client = _ScriptedClient(["NDVI 是归一化植被指数，范围 -1 到 1。"])
    _route_main(monkeypatch, client)

    output = await complete_turn(
        request=ChatRequest(
            messages=[ChatMessage(role="user", content="什么是 NDVI？")],
            use_rag=False,
            use_memory=False,
        ),
        user_id=None,
    )

    assert "NDVI 是归一化植被指数" in output.content
    # 单 Agent 的 TaskResult 没有 stop_reason（那是 Team 的概念），
    # ai_service._finish_reason_from_stop 对 None 兜底为 "stop"。
    assert output.stop_reason is None
    assert output.trace is not None


@pytest.mark.asyncio
async def test_model_client_is_closed_after_non_streaming_turn(monkeypatch) -> None:
    """非流式路径也必须关闭 model_client（与流式路径对称）。"""
    from app.agent.engine.service import complete_turn

    client = _ScriptedClient(["答复。"])
    closed: list[bool] = []

    async def _close():
        closed.append(True)

    client.close = _close  # type: ignore[method-assign]
    _route_main(monkeypatch, client)

    await complete_turn(
        request=ChatRequest(
            messages=[ChatMessage(role="user", content="什么是 NDVI？")],
            use_rag=False,
            use_memory=False,
        ),
        user_id=None,
    )

    assert closed, "非流式回合结束也必须关闭模型客户端"

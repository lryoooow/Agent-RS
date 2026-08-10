"""engine/service.py：流式正文的对外契约。

跑的是**真** SelectorGroupChat（只把模型客户端换成脚本），因为这里要验的几件事
都只在真实消息流里才会暴露：分片怎么切、跨专家的消息边界在哪、编排脚手架
在什么位置出现。用手搓的假消息序列测不出来。

三条不变量：

1. 用户看不到 `[DONE]` 与「进度自检」——它们是给终止判据和 selector 用的；
2. 跨领域链路里**每一步**的结论都要留在落库正文里；
3. 流式看到的正文与落库正文一致（否则刷新页面内容会变）。
"""
from __future__ import annotations

import pytest
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    ModelFamily,
    RequestUsage,
)

import app.agent.engine.orchestrator as orchestrator
from app.agent.engine.service import stream_turn_events

STEP_ONE = """已完成 NDVI 计算，均值 0.42。

进度自检：
- 计算 NDVI：已完成
- 生成报告：未完成（需 report_agent 来做）"""

STEP_TWO = """报告已生成，共 3 页。

进度自检：
- 计算 NDVI：已完成
- 生成报告：已完成

[DONE]"""


class _ScriptedClient(ChatCompletionClient):
    """selector 走 create()，领域 Agent 走 create_stream()。

    分片大小刻意取 8，好让 `进度自检` 与 `[DONE]` 被切断在分片中间——
    这正是标记漏进用户正文的真实成因。
    """

    def __init__(self, picks: list[str], replies: list[str], chunk: int = 8) -> None:
        self._picks = list(picks)
        self._replies = list(replies)
        self._chunk = chunk

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

    async def create(self, messages, **kwargs):
        pick = self._picks.pop(0) if self._picks else "spectral_agent"
        return CreateResult(
            finish_reason="stop",
            content=pick,
            usage=RequestUsage(prompt_tokens=0, completion_tokens=0),
            cached=False,
        )

    async def create_stream(self, messages, **kwargs):
        text = self._replies.pop(0) if self._replies else "好的。\n[DONE]"
        for i in range(0, len(text), self._chunk):
            yield text[i : i + self._chunk]
        yield CreateResult(
            finish_reason="stop",
            content=text,
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


async def _run(monkeypatch, picks: list[str], replies: list[str]):
    client = _ScriptedClient(picks, replies)
    monkeypatch.setattr(orchestrator, "build_model_client", lambda *a, **k: client)

    deltas: list[str] = []
    final = None
    async for kind, payload in stream_turn_events(
        query="先算 NDVI，再出报告", user_id=None, use_rag=False, use_memory=False
    ):
        if kind == "delta":
            deltas.append(payload)
        elif kind == "final":
            final = payload
    assert final is not None, "编排必须产出最终结果"
    return "".join(deltas), final


@pytest.mark.asyncio
async def test_scaffolding_never_reaches_the_user(monkeypatch) -> None:
    """实测踩到的坑：`[DONE]` 出现在用户看到的答复里。

    落库正文剥过标记，流式分片却是原样透传的，而前端默认走流式——
    于是用户亲眼看到 `[DONE]` 和整段「进度自检」。
    """
    streamed, final = await _run(
        monkeypatch, ["spectral_agent", "report_agent"], [STEP_ONE, STEP_TWO]
    )

    for text, where in ((streamed, "流式正文"), (final.content, "落库正文")):
        assert "[DONE]" not in text, f"{where}里不该出现终止标记"
        assert "进度自检" not in text, f"{where}里不该出现完成度自检清单"


@pytest.mark.asyncio
async def test_every_step_survives_in_the_saved_answer(monkeypatch) -> None:
    """跨领域链路里每位专家各产出一段真实结论，落库正文不能只留最后一条。

    只留最后一条时，用户在流式过程中看到了"NDVI 均值 0.42"，刷新页面却没了。
    """
    streamed, final = await _run(
        monkeypatch, ["spectral_agent", "report_agent"], [STEP_ONE, STEP_TWO]
    )

    assert "均值 0.42" in final.content, "第一步的结论不能从落库正文里消失"
    assert "报告已生成" in final.content
    assert "均值 0.42" in streamed


@pytest.mark.asyncio
async def test_streamed_body_matches_saved_body(monkeypatch) -> None:
    """流式看到的和落库的必须一致，否则刷新页面内容会变。"""
    streamed, final = await _run(
        monkeypatch, ["spectral_agent", "report_agent"], [STEP_ONE, STEP_TWO]
    )
    assert streamed == final.content


@pytest.mark.asyncio
async def test_single_expert_answer_is_unchanged(monkeypatch) -> None:
    """最常见的情况：一个专家直接作答，正文要原样流出去，不能被净化器动到。"""
    plain = "NDVI 全称是归一化植被指数，取值范围 -1 到 1。\n\n[DONE]"
    streamed, final = await _run(monkeypatch, ["spectral_agent"], [plain])

    expected = "NDVI 全称是归一化植被指数，取值范围 -1 到 1。"
    assert streamed == expected
    assert final.content == expected


# ------------------------------------------------------------------ 断连收尾


@pytest.mark.asyncio
async def test_disconnect_stops_the_rest_of_the_chain(monkeypatch) -> None:
    """前端断连后，跨领域链路不能继续一步一步往下跑。

    legacy 在 `ai_service` 的 finally 里 cancel(plan_task) 防的就是这个（H5）——
    用户已经走了还在烧 GPU。AutoGen 分支靠 `orchestrator._abandon` 里的外部终止。

    刻意**不**用 `cancellation_token.cancel()`：AutoGen 0.7.5 的
    `ChatAgentContainer.handle_request` 用的是 `except Exception`，接不住继承自
    BaseException 的 CancelledError，取消会让 runtime 的处理任务永久挂起
    （实测每次断连泄漏 2~5 个任务）。详见 `_abandon` 的说明。
    """
    import asyncio

    client = _ScriptedClient(["spectral_agent", "report_agent"], [STEP_ONE, STEP_TWO])
    monkeypatch.setattr(orchestrator, "build_model_client", lambda *a, **k: client)

    before = {id(t) for t in asyncio.all_tasks()}

    gen = stream_turn_events(
        query="先算 NDVI，再出报告", user_id=None, use_rag=False, use_memory=False
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
    client = _ScriptedClient(["spectral_agent"], ["答复。\n[DONE]"])
    closed: list[bool] = []

    async def _close():
        closed.append(True)

    client.close = _close  # type: ignore[method-assign]
    monkeypatch.setattr(orchestrator, "build_model_client", lambda *a, **k: client)

    async for _kind, _payload in stream_turn_events(
        query="NDVI 是什么", user_id=None, use_rag=False, use_memory=False
    ):
        pass

    assert closed, "回合结束必须关闭模型客户端"


@pytest.mark.asyncio
async def test_expert_with_only_scaffolding_leaves_no_blank_tail(monkeypatch) -> None:
    """有的专家整条消息都是脚手架（净化后为空）。

    这时不能因为"换了发言人"就先把分隔空行发出去——正文末尾会多一个空行，
    与落库正文对不上。分隔符必须等真的有下文才发。
    """
    only_scaffolding = "进度自检：\n- 计算 NDVI：已完成\n\n[DONE]"
    streamed, final = await _run(
        monkeypatch,
        ["spectral_agent", "report_agent"],
        ["已完成 NDVI 计算，均值 0.42。", only_scaffolding],
    )

    assert streamed == final.content
    assert streamed == "已完成 NDVI 计算，均值 0.42。"

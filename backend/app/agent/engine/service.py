"""AutoGen 链路的服务层入口：把编排结果整形成 `AIService` 需要的形状。

`ai_service.py` 按 `AGENT_ENGINE` 分流到这里，两条链路对外产出**完全同构**的结果，
所以上层的持久化、SSE 组装、错误映射都不用改。

## 为什么单独一层而不是直接改 ai_service

`ai_service.chat` / `stream_chat` 已经处理了持久化、断连取消、错误映射、
usage 统计等一堆正交的事。把 AutoGen 的逻辑塞进去会让那个函数变成两套流程交织，
迁移完成后想删 legacy 分支也难拆。这里把「跑一个回合并产出标准结果」独立出来，
`ai_service` 只做一次分流。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, AsyncIterator

from autogen_agentchat.messages import ModelClientStreamingChunkEvent
from autogen_core import CancellationToken

from app.agent.engine.event_bridge import (
    BridgeState,
    emit_context_assembled,
    emit_final_answering,
    emit_geospatial_ready,
    translate,
)
from app.agent.engine.orchestrator import (
    AnswerStreamSanitizer,
    OrchestrationResult,
    run_turn,
    stream_turn,
)
from app.agent.types import AgentEvent, AgentTrace

logger = logging.getLogger(__name__)


@dataclass
class AutogenTurnOutput:
    """一个回合的完整产出，字段与 legacy 的 AgentPlanResult + 正文合并后对齐。"""

    content: str
    trace: AgentTrace
    retrieved_chunks: int = 0
    rag_trace: dict | None = None
    geospatial_result: Any = None
    tool_result: Any = None
    used_tool: bool = False
    stop_reason: str | None = None


async def complete_turn(
    *,
    query: str,
    user_id: str | None,
    use_rag: bool,
    use_memory: bool,
    cancellation_token: CancellationToken | None = None,
) -> AutogenTurnOutput:
    """非流式：跑完一个回合。"""
    trace = AgentTrace(enabled=True)
    state = BridgeState()
    emit_context_assembled(trace=trace, state=state)

    result = await run_turn(
        query,
        user_id=user_id,
        use_rag=use_rag,
        use_memory=use_memory,
        cancellation_token=cancellation_token,
    )
    _replay_messages_into_trace(result, trace=trace, state=state)
    return _to_output(result, trace=trace, state=state)


async def stream_turn_events(
    *,
    query: str,
    user_id: str | None,
    use_rag: bool,
    use_memory: bool,
    cancellation_token: CancellationToken | None = None,
) -> AsyncIterator[tuple[str, Any]]:
    """流式：逐个 yield `(kind, payload)`。

    kind 取值：
    - `"status"` → payload 是 `AgentEvent`，调用方转成 agent_status SSE
    - `"delta"`  → payload 是正文分片字符串
    - `"final"`  → payload 是 `AutogenTurnOutput`，回合结束

    正文分片与状态事件分开，是因为前端把它们当两类事件处理
    （状态渲染成工具气泡，分片拼成答复正文）。

    分片经 `AnswerStreamSanitizer` 过滤：`[DONE]` 与「进度自检」是编排脚手架，
    落库正文里剥掉了，流式正文里也必须剥掉，否则用户会亲眼看到 `[DONE]`。

    ## 断连要停掉后续步骤

    调用方没跑完就把这个生成器丢掉（前端断连时 FastAPI 就是这么做的），
    GeneratorExit 会打到当前 yield 点。此时必须**显式**关闭底层的编排流，
    触发 `orchestrator._abandon` 去喊停团队；否则那条链路会继续一步一步往下跑，
    用户已经走了还在烧 GPU（legacy 分支的 H5 修复防的就是这个）。

    这里显式 `aclose()` 而不是靠 asyncio 的异步生成器终结器，是为了让收尾**确定性地**
    立刻发生，而不是等下一次 GC。
    """
    trace = AgentTrace(enabled=True)
    state = BridgeState()

    yield "status", emit_context_assembled(trace=trace, state=state)

    seen_geospatial = False
    sanitizer = AnswerStreamSanitizer()
    # 跨领域链路里每位专家是一条独立消息，靠 full_message_id 认边界：
    # 换消息时要先把上一条扣住的尾巴 flush 掉，再补一个空行，
    # 否则两位专家的正文会直接粘成一句（"…需 report_agent 来做）报告已生成。"）。
    #
    # 分隔符**延迟到真的有下文时才发**：有的消息整条都是脚手架（净化后为空），
    # 立刻发就会在正文末尾留一个空行，与落库正文对不上。
    current_message_id: str | None = None
    started_body = False
    pending_separator = False

    def _body(piece: str) -> list[str]:
        """把一段正文变成待发的 delta 列表，顺带处理延迟分隔符。"""
        nonlocal started_body, pending_separator
        if not piece:
            return []
        out = ["\n\n", piece] if pending_separator and started_body else [piece]
        pending_separator = False
        started_body = True
        return out

    turns = stream_turn(
        query,
        user_id=user_id,
        use_rag=use_rag,
        use_memory=use_memory,
        cancellation_token=cancellation_token,
    )
    try:
        async for item in turns:
            if isinstance(item, OrchestrationResult):
                for piece in _body(sanitizer.flush()):
                    yield "delta", piece
                # 图层产物走回合状态而非工具返回值，所以在收尾时补发事件。
                if not seen_geospatial and item.geospatial_result is not None:
                    yield "status", emit_geospatial_ready(
                        trace=trace,
                        state=state,
                        tool_name=_last_tool_name(item),
                        result_type=_result_type(item.geospatial_result),
                    )
                yield "status", emit_final_answering(
                    trace=trace, state=state, used_tool=item.used_tool
                )
                yield "final", _to_output(item, trace=trace, state=state)
                return

            if isinstance(item, ModelClientStreamingChunkEvent):
                if item.full_message_id != current_message_id:
                    for piece in _body(sanitizer.flush()):
                        yield "delta", piece
                    if current_message_id is not None:
                        pending_separator = True
                    current_message_id = item.full_message_id
                for piece in _body(sanitizer.feed(item.content)):
                    yield "delta", piece
                continue

            for event in translate(item, trace=trace, state=state):
                yield "status", event
    finally:
        # 正常跑完时这是个 no-op（生成器已耗尽）；断连时它触发 orchestrator._abandon，
        # 让团队停在下一个消息边界，不再启动后续步骤。
        await turns.aclose()


def _replay_messages_into_trace(
    result: OrchestrationResult, *, trace: AgentTrace, state: BridgeState
) -> None:
    """非流式路径：事后把消息序列翻译成 trace，保证两种模式的 agent_trace 一致。"""
    for message in result.messages:
        translate(message, trace=trace, state=state)
    if result.geospatial_result is not None:
        emit_geospatial_ready(
            trace=trace,
            state=state,
            tool_name=_last_tool_name(result),
            result_type=_result_type(result.geospatial_result),
        )
    emit_final_answering(trace=trace, state=state, used_tool=result.used_tool)


def _to_output(
    result: OrchestrationResult, *, trace: AgentTrace, state: BridgeState
) -> AutogenTurnOutput:
    return AutogenTurnOutput(
        content=result.content,
        trace=trace,
        retrieved_chunks=result.retrieved_chunks,
        rag_trace=result.rag_trace,
        geospatial_result=result.geospatial_result,
        tool_result=result.tool_result,
        used_tool=result.used_tool,
        stop_reason=result.stop_reason,
    )


def _last_tool_name(result: OrchestrationResult) -> str:
    state = result.turn_state
    if state and state.invocations:
        return state.invocations[-1].name
    return "unknown"


def _result_type(geospatial_result: Any) -> str:
    if isinstance(geospatial_result, dict):
        return str(geospatial_result.get("type") or "unknown")
    return str(getattr(geospatial_result, "type", "unknown"))

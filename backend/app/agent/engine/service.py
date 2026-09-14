"""AutoGen 服务层入口：把团队事件与结果整形成 `AIService` 的稳定契约。

编排逻辑留在本层；`AIService` 只负责持久化、SSE 组装、错误映射和 usage 记录。
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
    OrchestrationMetadata,
    OrchestrationResult,
    run_turn,
    stream_turn,
)
from app.agent.engine.input import build_turn_input
from app.agent.engine.turn_context import current_turn_state
from app.agent.config import ResolvedAIConfig
from app.agent.search.credentials import tavily_key_scope
from app.agent.types import AgentEvent, AgentTrace
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)


@dataclass
class AutogenTurnOutput:
    """一个 AutoGen 回合的完整产出。"""

    content: str
    trace: AgentTrace
    retrieved_chunks: int = 0
    rag_trace: dict | None = None
    geospatial_result: Any = None
    tool_result: Any = None
    used_tool: bool = False
    stop_reason: str | None = None
    usage: dict | None = None
    map_target: dict | None = None
    framework: str = "autogen"
    strategy: str = "main"
    flow_name: str | None = None
    route_reason: str = ""


async def complete_turn(
    *,
    request: ChatRequest,
    user_id: str | None,
    cancellation_token: CancellationToken | None = None,
    config: ResolvedAIConfig | None = None,
) -> AutogenTurnOutput:
    """非流式：跑完一个回合。"""
    trace = AgentTrace(enabled=True)
    state = BridgeState()
    emit_context_assembled(trace=trace, state=state)
    turn_input = await build_turn_input(request, user_id=user_id)

    with tavily_key_scope(request.tavily_api_key()):
        result = await run_turn(
            turn_input,
            user_id=user_id,
            use_rag=request.use_rag,
            use_memory=request.use_memory,
            cancellation_token=cancellation_token,
            config=config,
        )
    _emit_strategy(result, trace=trace, state=state)
    _replay_messages_into_trace(result, trace=trace, state=state)
    return _to_output(result, trace=trace, state=state)


async def stream_turn_events(
    *,
    request: ChatRequest,
    user_id: str | None,
    cancellation_token: CancellationToken | None = None,
    config: ResolvedAIConfig | None = None,
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
    用户已经走了还在烧 GPU。

    这里显式 `aclose()` 而不是靠 asyncio 的异步生成器终结器，是为了让收尾**确定性地**
    立刻发生，而不是等下一次 GC。
    """
    trace = AgentTrace(enabled=True)
    state = BridgeState()

    yield "status", emit_context_assembled(trace=trace, state=state)
    turn_input = await build_turn_input(request, user_id=user_id)

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

    tavily_scope = tavily_key_scope(request.tavily_api_key())
    tavily_scope.__enter__()
    turns = stream_turn(
        turn_input,
        user_id=user_id,
        use_rag=request.use_rag,
        use_memory=request.use_memory,
        cancellation_token=cancellation_token,
        config=config,
    )
    _last_map: dict | None = None
    try:
        async for item in turns:
            if isinstance(item, OrchestrationMetadata):
                yield "status", trace.add(
                    "routing_selected",
                    "已选择 AutoGen 编排策略",
                    framework=item.framework,
                    strategy=item.strategy,
                    flow_name=item.flow_name,
                    parent_run_id=state.parent_run_id,
                )
                continue
            # 对话控图：look_at_location 一解析完（turn_state.map_target 被写）就 mid-stream 发出。
            _ts = current_turn_state()
            if _ts is not None and _ts.map_target is not None and _ts.map_target is not _last_map:
                _last_map = _ts.map_target
                yield "map_control", dict(_ts.map_target)
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
        try:
            await turns.aclose()
        finally:
            tavily_scope.__exit__(None, None, None)


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
        usage=result.usage,
        map_target=result.map_target,
        framework=result.framework,
        strategy=result.strategy,
        flow_name=result.flow_name,
        route_reason=result.route_reason,
    )


def _emit_strategy(
    result: OrchestrationResult, *, trace: AgentTrace, state: BridgeState
) -> AgentEvent:
    return trace.add(
        "routing_selected",
        "已选择 AutoGen 编排策略",
        framework=result.framework,
        strategy=result.strategy,
        flow_name=result.flow_name,
        parent_run_id=state.parent_run_id,
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

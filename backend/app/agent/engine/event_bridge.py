"""AutoGen 消息流 → 现有 SSE 事件的翻译层。

本层定义后端到前端的稳定 AutoGen 事件契约。`agent_trace` 的结构与
`execution_kind` / `dispatch_kind` / `agent_name` / `parent_run_id` / `child_run_id`
五个字段保持稳定；Selector 选人、多步工具循环和跨领域交棒都映射为明确的框架事件。

## 映射表

| AutoGen 消息                     | 现有 stage                                   | 前端表现 |
| -------------------------------- | -------------------------------------------- | -------- |
| 开始                             | `context_assembled`                          | 隐藏 |
| `SelectSpeakerEvent`             | `agent_selected`                             | 隐藏（调度噪声） |
| `ToolCallRequestEvent`           | `tool_requested` → `child_agent_running` → `tool_execution_started` | 转圈 |
| `ToolCallExecutionEvent`（成功） | `tool_execution_completed` → `tool_context_ready` | 打勾 |
| `ToolCallExecutionEvent`（失败） | `tool_execution_failed`                      | 红叉 |
| 产出图层                         | `geospatial_result_ready`                    | 打勾 |
| `ModelClientStreamingChunkEvent` | —（走 delta 通道，不是 agent_status）         | 正文流式 |
| 结束                             | `final_answering`                            | 隐藏 |

## 多步链路怎么落到"单工具"的契约上

前端的气泡是按 `child_run_id` 区分的。多步链路里每个工具调用分配一个新的
`child_run_id`，`parent_run_id` 用发起它的领域 Agent 的 run id——正好形成
「顶层 → 领域 Agent → 工具执行」的三层链。前端不需要知道这次有几步。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from autogen_agentchat.messages import (
    ModelClientStreamingChunkEvent,
    SelectSpeakerEvent,
    TextMessage,
    ToolCallExecutionEvent,
    ToolCallRequestEvent,
)

from app.agent.engine.agents import agent_label
from app.agent.engine.search import SEARCH_AGENT_LABEL, SEARCH_AGENT_NAME
from app.agent.prompting.scenarios import (
    tool_ready_label,
    tool_request_label,
    tool_running_label,
)
from app.agent.types import AgentEvent, AgentTrace

logger = logging.getLogger(__name__)


@dataclass
class BridgeState:
    """跨消息保持的状态：run id 分配与工具调用配对。"""

    parent_run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    # 领域 Agent 名 -> 它的 run id。同一个 Agent 多次发言复用同一个 id，
    # 前端才能把它的多个工具气泡归到一组。
    agent_run_ids: dict[str, str] = field(default_factory=dict)
    # 工具调用 id -> (工具名, child_run_id)。请求与结果分属两条消息，靠这个配对。
    pending_calls: dict[str, tuple[str, str]] = field(default_factory=dict)

    def run_id_for(self, agent_name: str) -> str:
        return self.agent_run_ids.setdefault(agent_name, uuid.uuid4().hex)


def _agent_label(agent_name: str) -> str:
    if agent_name == SEARCH_AGENT_NAME:
        return SEARCH_AGENT_LABEL
    return agent_label(agent_name)


def translate(
    message: Any,
    *,
    trace: AgentTrace,
    state: BridgeState,
) -> list[AgentEvent]:
    """把一条 AutoGen 消息翻译成 0..n 条现有格式的 AgentEvent。

    未知消息类型返回空列表——**不能**因为 AutoGen 加了新消息类型就让整条链路挂掉。
    """
    if isinstance(message, ModelClientStreamingChunkEvent):
        # 正文分片走 delta 通道，不是 agent_status；调用方单独处理。
        return []

    if isinstance(message, SelectSpeakerEvent):
        return [
            trace.add(
                "agent_selected",
                f"由{_agent_label(_first(message.content))}处理",
                agent_name=_first(message.content),
                dispatch_kind="agent",
                execution_kind="agent",
                parent_run_id=state.parent_run_id,
            )
        ]

    if isinstance(message, ToolCallRequestEvent):
        return _on_tool_request(message, trace=trace, state=state)

    if isinstance(message, ToolCallExecutionEvent):
        return _on_tool_result(message, trace=trace, state=state)

    return []


def _on_tool_request(
    message: ToolCallRequestEvent, *, trace: AgentTrace, state: BridgeState
) -> list[AgentEvent]:
    agent_name = message.source
    agent_run_id = state.run_id_for(agent_name)
    events: list[AgentEvent] = []

    for call in message.content:
        child_run_id = uuid.uuid4().hex
        state.pending_calls[call.id] = (call.name, child_run_id)
        common = {
            "tool_name": call.name,
            "agent_name": agent_name,
            "domain": agent_name,
            "domain_label": _agent_label(agent_name),
            "parent_run_id": agent_run_id,
            "child_run_id": child_run_id,
            "execution_kind": "tool",
            "dispatch_kind": "tool",
        }
        # 前端据此把工具气泡从“请求”推进到“执行中”。
        events.append(trace.add("tool_requested", tool_request_label(call.name), **common))
        events.append(trace.add("child_agent_running", tool_running_label(call.name), **common))
        events.append(
            trace.add("tool_execution_started", tool_running_label(call.name), **common)
        )
    return events


def _on_tool_result(
    message: ToolCallExecutionEvent, *, trace: AgentTrace, state: BridgeState
) -> list[AgentEvent]:
    agent_name = message.source
    agent_run_id = state.run_id_for(agent_name)
    events: list[AgentEvent] = []

    for result in message.content:
        tool_name, child_run_id = state.pending_calls.pop(
            result.call_id, (result.name or "unknown", uuid.uuid4().hex)
        )
        common = {
            "tool_name": tool_name,
            "agent_name": agent_name,
            "domain": agent_name,
            "domain_label": _agent_label(agent_name),
            "parent_run_id": agent_run_id,
            "child_run_id": child_run_id,
            "execution_kind": "tool",
            "dispatch_kind": "tool",
        }
        if result.is_error:
            events.append(trace.add("tool_execution_failed", "工具执行失败", **common))
        else:
            events.append(trace.add("tool_execution_completed", "工具执行完成", **common))
        events.append(
            trace.add(
                "tool_context_ready",
                tool_ready_label(tool_name),
                tool_context_chars=len(str(result.content or "")),
                error="tool_error" if result.is_error else None,
                **common,
            )
        )
    return events


def emit_geospatial_ready(
    *, trace: AgentTrace, state: BridgeState, tool_name: str, result_type: str
) -> AgentEvent:
    """图层产出事件。

    单独暴露而不是在 `_on_tool_result` 里判断，是因为图层产物走的是回合状态
    （`turn_context`）而不是工具返回值——AutoGen 的工具返回值只有给模型看的文本。
    调用方在回合结束时对比 turn_state 决定发不发。
    """
    return trace.add(
        "geospatial_result_ready",
        "地图图层结果已生成",
        tool_name=tool_name,
        result_type=result_type,
        agent_name="tool_child_agent",
        parent_run_id=state.parent_run_id,
        child_run_id=uuid.uuid4().hex,
        execution_kind="tool",
        dispatch_kind="tool",
    )


def emit_context_assembled(
    *, trace: AgentTrace, state: BridgeState, retrieved_chunks: int = 0, rag_trace: dict | None = None
) -> AgentEvent:
    return trace.add(
        "context_assembled",
        "上下文已装配",
        retrieved_chunks=retrieved_chunks,
        rag_trace=rag_trace,
        parent_run_id=state.parent_run_id,
    )


def emit_final_answering(
    *, trace: AgentTrace, state: BridgeState, tool_context_chars: int = 0, used_tool: bool = False
) -> AgentEvent:
    return trace.add(
        "final_answering",
        "正在组织回答",
        tool_context_chars=tool_context_chars,
        dispatch_kind="tool" if used_tool else "direct",
        parent_run_id=state.parent_run_id,
    )


def _first(content: Any) -> str:
    if isinstance(content, list) and content:
        return str(content[0])
    return str(content)

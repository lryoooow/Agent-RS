"""engine/event_bridge.py：AutoGen 消息 → SSE 契约。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import get_args

import pytest
from autogen_agentchat.messages import (
    ModelClientStreamingChunkEvent,
    SelectSpeakerEvent,
    ToolCallExecutionEvent,
    ToolCallRequestEvent,
)
from autogen_core import FunctionCall
from autogen_core.models import FunctionExecutionResult

from app.agent.engine.event_bridge import (
    BridgeState,
    emit_context_assembled,
    emit_final_answering,
    emit_geospatial_ready,
    translate,
)
from app.agent.types import AgentStage, AgentTrace

BACKEND_STAGES = set(get_args(AgentStage))

REQUIRED_TOOL_FIELDS = {
    "execution_kind",
    "dispatch_kind",
    "agent_name",
    "parent_run_id",
    "child_run_id",
}


def _call(name: str, call_id: str) -> FunctionCall:
    return FunctionCall(id=call_id, name=name, arguments="{}")


def _request(agent: str, *calls: FunctionCall) -> ToolCallRequestEvent:
    return ToolCallRequestEvent(content=list(calls), source=agent)


def _result(agent: str, call_id: str, name: str, *, error: bool = False):
    return ToolCallExecutionEvent(
        content=[
            FunctionExecutionResult(
                call_id=call_id, content="结果文本", is_error=error, name=name
            )
        ],
        source=agent,
    )


@pytest.fixture
def bridge():
    return AgentTrace(enabled=True), BridgeState()


def test_every_emitted_stage_is_known_to_the_frontend(bridge) -> None:
    """事件桥绝不能发明前端不认识的 stage——那会让气泡显示不出来。"""
    trace, state = bridge
    events = []
    events += translate(SelectSpeakerEvent(content=["spectral_agent"], source="selector"), trace=trace, state=state)
    events += translate(_request("spectral_agent", _call("calculate_ndvi", "c1")), trace=trace, state=state)
    events += translate(_result("spectral_agent", "c1", "calculate_ndvi"), trace=trace, state=state)
    events.append(emit_context_assembled(trace=trace, state=state))
    events.append(emit_final_answering(trace=trace, state=state))
    events.append(
        emit_geospatial_ready(trace=trace, state=state, tool_name="calculate_ndvi", result_type="ndvi")
    )

    unknown = {e.stage for e in events} - BACKEND_STAGES
    assert not unknown, f"事件桥发出了 AgentStage 未声明的 stage: {unknown}"


def test_backend_and_frontend_agent_stage_unions_are_identical() -> None:
    """跨语言契约不能靠两份手写清单碰巧一致。"""
    frontend_types = (
        Path(__file__).resolve().parents[3] / "Agent-frontend/src/app/types.ts"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"export type AgentStatus\s*=\s*(.*?);",
        frontend_types,
        flags=re.DOTALL,
    )
    assert match is not None
    frontend_stages = set(re.findall(r'"([a-z_]+)"', match.group(1)))
    assert frontend_stages == BACKEND_STAGES


def test_tool_request_emits_the_three_step_sequence(bridge) -> None:
    """工具请求发出三段状态，前端据此把气泡推进到“转圈”。"""
    trace, state = bridge
    events = translate(_request("spectral_agent", _call("calculate_ndvi", "c1")), trace=trace, state=state)
    assert [e.stage for e in events] == [
        "tool_requested",
        "child_agent_running",
        "tool_execution_started",
    ]


def test_tool_events_carry_all_contract_fields(bridge) -> None:
    trace, state = bridge
    events = translate(_request("spectral_agent", _call("calculate_ndvi", "c1")), trace=trace, state=state)
    events += translate(_result("spectral_agent", "c1", "calculate_ndvi"), trace=trace, state=state)

    for event in events:
        missing = REQUIRED_TOOL_FIELDS - set(event.metadata)
        assert not missing, f"{event.stage} 缺少契约字段 {missing}"
        assert event.metadata["execution_kind"] == "tool"
        assert event.metadata["dispatch_kind"] == "tool"


def test_request_and_result_share_the_same_child_run_id(bridge) -> None:
    """前端靠 child_run_id 把"开始"和"完成"配成同一个气泡，配错就会多出一个气泡。"""
    trace, state = bridge
    started = translate(_request("spectral_agent", _call("calculate_ndvi", "c1")), trace=trace, state=state)
    finished = translate(_result("spectral_agent", "c1", "calculate_ndvi"), trace=trace, state=state)

    ids = {e.metadata["child_run_id"] for e in started}
    assert len(ids) == 1
    assert {e.metadata["child_run_id"] for e in finished} == ids


def test_multi_step_chain_groups_by_agent_but_separates_by_tool(bridge) -> None:
    """多步链路：同一 Agent 的多个工具共享 parent_run_id，各自有独立 child_run_id。

    这样前端能把"指数分析专家做了两件事"渲染成一组两个气泡，
    而不需要知道这轮到底跑了几步。
    """
    trace, state = bridge
    events = []
    for i, tool in enumerate(("raster_inspect", "calculate_ndvi")):
        events += translate(_request("spectral_agent", _call(tool, f"c{i}")), trace=trace, state=state)

    parents = {e.metadata["parent_run_id"] for e in events}
    children = {e.metadata["child_run_id"] for e in events}
    assert len(parents) == 1, "同一 Agent 的工具必须归到同一个 parent_run_id"
    assert len(children) == 2, "不同工具必须有各自的 child_run_id"


def test_cross_domain_handoff_uses_distinct_parent_run_ids(bridge) -> None:
    """跨领域交棒后 parent_run_id 要换，前端才能分成两组气泡。"""
    trace, state = bridge
    a = translate(_request("spectral_agent", _call("calculate_ndvi", "c1")), trace=trace, state=state)
    b = translate(_request("report_agent", _call("generate_report", "c2")), trace=trace, state=state)

    assert a[0].metadata["parent_run_id"] != b[0].metadata["parent_run_id"]


def test_failed_tool_maps_to_error_stage(bridge) -> None:
    trace, state = bridge
    translate(_request("spectral_agent", _call("calculate_ndvi", "c1")), trace=trace, state=state)
    events = translate(_result("spectral_agent", "c1", "calculate_ndvi", error=True), trace=trace, state=state)

    assert events[0].stage == "tool_execution_failed"


def test_streaming_chunks_do_not_become_agent_status(bridge) -> None:
    """正文分片走 delta 通道；若误发成 agent_status，前端会把正文当状态渲染。"""
    trace, state = bridge
    events = translate(
        ModelClientStreamingChunkEvent(content="NDVI 是", source="spectral_agent"),
        trace=trace,
        state=state,
    )
    assert events == []


def test_unknown_message_type_is_ignored_not_fatal(bridge) -> None:
    """AutoGen 加新消息类型时不能让整条链路挂掉。"""
    trace, state = bridge

    class SomethingNew:
        source = "x"

    assert translate(SomethingNew(), trace=trace, state=state) == []


def test_trace_payload_shape_is_stable() -> None:
    """agent_trace 的 JSON 结构是前端契约，字段名不能变。"""
    trace = AgentTrace(enabled=True)
    state = BridgeState()
    translate(_request("spectral_agent", _call("calculate_ndvi", "c1")), trace=trace, state=state)

    payload = trace.model_dump()
    assert set(payload) == {"enabled", "events"}
    event = payload["events"][0]
    assert set(event) == {"stage", "label", "metadata", "elapsed_ms"}
    json.dumps(payload, ensure_ascii=False)  # 必须可序列化进 SSE

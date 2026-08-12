import json
from typing import Any, Iterator

ANSWER_DELTA_MAX_CHARS = 6  # 仅做轻量切块，不再人为拖慢
ANALYSIS_STATUS_LABELS = {
    "analyzing": "正在思考中…",
    "preparing": "正在梳理结果…",
    "answering": "正在生成回复…",
    "complete": "思考完成",
}
AGENT_STATUS_LABELS = {
    "context_assembled": "上下文已装配",
    "routing_selected": "已选择 AutoGen 编排策略",
    "agent_selected": "已选择处理 Agent",
    "tool_requested": "准备调用工具",
    "child_agent_running": "正在执行工具",
    "tool_execution_started": "工具执行已开始",
    "tool_execution_completed": "工具执行完成",
    "tool_execution_failed": "工具执行失败",
    "tool_context_ready": "工具结果已整理",
    "geospatial_result_ready": "地图图层结果已生成",
    "final_answering": "正在生成最终回答",
}


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def analysis_status_event(status: str) -> str:
    return sse_event(
        "analysis_status",
        {
            "status": status,
            "label": ANALYSIS_STATUS_LABELS[status],
        },
    )


def agent_status_event(status: str, *, label: str | None = None, **metadata: Any) -> str:
    # 根因修复：执行阶段（child_agent_running）的具体工具名在 AgentEvent.label 里
    # （由 AutoGen event bridge 经 tool_running_label 算出），优先透传它；
    # 仅当事件没带 label 时，才回退到按 status 查静态字典——否则 child_agent_running
    # 永远被映射回宽泛的"正在执行工具"，具体工具名在到达前端前被丢弃。
    return sse_event(
        "agent_status",
        {
            "status": status,
            "label": label or AGENT_STATUS_LABELS.get(status, status),
            **metadata,
        },
    )


def iter_answer_delta_parts(content_parts: list[str]) -> Iterator[str]:
    for value in content_parts:
        if not value:
            continue
        for cursor in range(0, len(value), ANSWER_DELTA_MAX_CHARS):
            part = value[cursor : cursor + ANSWER_DELTA_MAX_CHARS]
            if part:
                yield part

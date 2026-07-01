import json
from typing import Any, AsyncIterator, Iterator

from app.agent.errors import AIError, map_provider_error
from app.agent.reasoning import ThinkTagParser
from app.schemas.chat import Usage

REASONING_FIELDS = ("reasoning_content", "reasoning", "thinking", "thought")
ANSWER_DELTA_MAX_CHARS = 6  # 仅做轻量切块，不再人为拖慢
ANALYSIS_STATUS_LABELS = {
    "analyzing": "正在思考中…",
    "preparing": "正在梳理结果…",
    "answering": "正在生成回复…",
    "complete": "思考完成",
}
AGENT_STATUS_LABELS = {
    "context_assembled": "上下文已装配",
    "planning": "正在判断是否需要联网",
    "planning_fallback": "规划模型失败，正在兜底",
    "planner_started": "正在规划能力调用",
    "planner_completed": "能力规划已完成",
    "planner_invalid": "能力规划无效",
    "planner_selected": "已选择能力调用",
    "planner_no_call": "无需调用能力",
    "plan_validation_failed": "能力规划校验失败",
    "capability_guard_rejected": "能力调用被拒绝",
    "cache_hit_skip": "命中无需搜索的缓存",
    "cache_hit_search": "命中需要搜索的缓存",
    "tool_requested": "准备调用工具",
    "child_agent_running": "正在执行工具",
    "tool_execution_started": "工具执行已开始",
    "tool_execution_completed": "工具执行完成",
    "tool_execution_failed": "工具执行失败",
    "tool_fallback_used": "工具使用了本地回退",
    "tool_context_ready": "工具结果已整理",
    "geospatial_result_ready": "地图图层结果已生成",
    "final_answering": "正在生成最终回答",
    "direct_answer": "无需调用工具",
    "tool_unavailable": "工具不可用",
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
    # （由 child.py/domain_agents.py 经 tool_running_label 算出），优先透传它；
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


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _normalize_usage(usage: Any) -> dict[str, int | None] | None:
    if usage is None:
        return None
    normalized = Usage(
        input_tokens=_read(usage, "prompt_tokens", None),
        output_tokens=_read(usage, "completion_tokens", None),
        total_tokens=_read(usage, "total_tokens", None),
    )
    return normalized.model_dump(exclude_none=True)


def normalize_stream_chunk(chunk: Any) -> dict[str, Any]:
    choices = _read(chunk, "choices", []) or []
    first_choice = choices[0] if choices else None
    delta = _read(first_choice, "delta", {}) if first_choice else {}
    reasoning = next((_read(delta, field, None) for field in REASONING_FIELDS if _read(delta, field, None)), None)

    return {
        "content": _read(delta, "content", None),
        "reasoning": reasoning,
        "finish_reason": _read(first_choice, "finish_reason", None) if first_choice else None,
        "usage": _normalize_usage(_read(chunk, "usage", None)),
    }


async def stream_sse_events(stream: AsyncIterator[Any]) -> AsyncIterator[str]:
    finish_reason: str | None = None
    usage: dict[str, int | None] | None = None
    think_parser = ThinkTagParser()
    complete_sent = False
    visible_delta_sent = False

    try:
        async for chunk in stream:
            normalized = normalize_stream_chunk(chunk)
            content = normalized["content"]

            if content:
                for channel, value in think_parser.feed(content):
                    if channel == "reasoning":
                        continue
                    for part in iter_answer_delta_parts([value]):
                        if not complete_sent:
                            yield analysis_status_event("complete")
                            complete_sent = True
                        yield sse_event("delta", {"content": part})
                        visible_delta_sent = True

            if normalized["finish_reason"]:
                finish_reason = normalized["finish_reason"]
            if normalized["usage"]:
                usage = normalized["usage"]
    except Exception as exc:
        error = exc if isinstance(exc, AIError) else map_provider_error(exc)
        if visible_delta_sent:
            yield sse_event(
                "done",
                {
                    "finish_reason": "error",
                    "error": {"code": error.code, "message": error.message},
                },
            )
            return
        yield sse_event("error", {"code": error.code, "message": error.message})
        return

    for channel, value in think_parser.flush():
        if channel == "reasoning":
            continue
        for part in iter_answer_delta_parts([value]):
            if not complete_sent:
                yield analysis_status_event("complete")
                complete_sent = True
            yield sse_event("delta", {"content": part})
            visible_delta_sent = True

    if not complete_sent:
        yield analysis_status_event("complete")

    done_payload: dict[str, Any] = {"finish_reason": finish_reason}
    if usage:
        done_payload["usage"] = usage
    yield sse_event("done", done_payload)

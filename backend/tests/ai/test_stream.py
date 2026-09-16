"""框架无关的 SSE 辅助函数。模型分片由 AutoGen event bridge 负责。"""

import json

from app.agent.stream import agent_status_event, analysis_status_event, sse_event


def _payload(event: str) -> dict:
    for line in event.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError(f"no data line in event: {event!r}")


def test_sse_event_serializes_unicode() -> None:
    event = sse_event("delta", {"content": "你好"})
    assert event.startswith("event: delta\n")
    assert _payload(event) == {"content": "你好"}


def test_analysis_status_event_has_label() -> None:
    payload = _payload(analysis_status_event("answering"))
    assert payload["status"] == "answering"
    assert payload["label"]


def test_agent_status_event_uses_explicit_label() -> None:
    payload = _payload(
        agent_status_event(
            "child_agent_running",
            label="正在进行 SAM3 实例分割",
            tool_name="segment_instances",
            elapsed_ms=1234,
        )
    )
    assert payload["label"] == "正在进行 SAM3 实例分割"
    assert payload["tool_name"] == "segment_instances"
    assert payload["elapsed_ms"] == 1234


def test_agent_status_event_falls_back_for_unknown_stage() -> None:
    payload = _payload(agent_status_event("some_unregistered_stage"))
    assert payload == {
        "status": "some_unregistered_stage",
        "label": "some_unregistered_stage",
    }

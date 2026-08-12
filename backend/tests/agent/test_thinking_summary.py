from app.agent.thinking_summary import SUMMARY_LABELS, ThinkingSummaryTracker


def test_summary_is_fixed_and_deduplicated() -> None:
    tracker = ThinkingSummaryTracker()

    first = tracker.advance_for_agent_event("tool_requested")
    duplicate = tracker.advance_for_agent_event("tool_execution_started")

    assert first == {"stage": "tool", "label": SUMMARY_LABELS["tool"]}
    assert duplicate is None


def test_summary_never_accepts_agent_label_or_model_text() -> None:
    tracker = ThinkingSummaryTracker()
    secret = "模型内部推理：用户的隐藏资料"

    event = tracker.advance_for_agent_event("routing_selected")

    assert event == {"stage": "routing", "label": SUMMARY_LABELS["routing"]}
    assert secret not in str(event)

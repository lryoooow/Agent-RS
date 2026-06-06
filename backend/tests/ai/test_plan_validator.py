from __future__ import annotations

import json
from pathlib import Path

from app.agent.llm_planner import PlannerDecision
from app.agent.plan_validator import PlanValidator
from app.agent.routing import AgentRoute
from app.core.settings import get_settings


def reset_settings() -> None:
    get_settings.cache_clear()


def _owned_imagery(root: Path, imagery_id: str, owner_user_id: str) -> None:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    (imagery_dir / "metadata.json").write_text(
        json.dumps({"filename": "sample.tif", "owner_user_id": owner_user_id}),
        encoding="utf-8",
    )


def test_validator_accepts_web_search_agent(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    decision = PlannerDecision(
        action="call",
        capability="web_search",
        arguments={"query": "明天杭州天气", "reason": "需要实时天气"},
        reason="needs_current_weather",
    )

    plan = PlanValidator().validate(
        decision,
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_agents=("web_search",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.agent_call is not None
    assert plan.agent_call.name == "web_search"


def test_validator_rejects_unknown_capability() -> None:
    plan = PlanValidator().validate(
        PlannerDecision(action="call", capability="missing", arguments={}, reason="bad"),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_agents=("web_search",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.action == "none"
    assert plan.validation_error == "unknown_capability"


def test_validator_rejects_route_disallowed_capability(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    plan = PlanValidator().validate(
        PlannerDecision(
            action="call",
            capability="web_search",
            arguments={"query": "明天天气", "reason": "fresh"},
            reason="fresh",
        ),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_tools=("calculate_ndvi",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.action == "none"
    assert plan.validation_error == "capability_not_allowed_by_route"


def test_validator_rejects_invalid_arguments(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    plan = PlanValidator().validate(
        PlannerDecision(action="call", capability="web_search", arguments={"query": ""}, reason="bad"),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_agents=("web_search",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.action == "none"
    assert "validation errors" in (plan.validation_error or "")


def test_validator_rejects_other_user_imagery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_settings()
    _owned_imagery(tmp_path, "94e758f38ede", "other-user")

    plan = PlanValidator().validate(
        PlannerDecision(
            action="call",
            capability="calculate_ndvi",
            arguments={"imagery_id": "94e758f38ede"},
            reason="ndvi",
        ),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_tools=("calculate_ndvi",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.action == "none"
    assert plan.validation_error == "imagery_not_found_or_forbidden"


def test_validator_accepts_owned_imagery_tool(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_settings()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)

    plan = PlanValidator().validate(
        PlannerDecision(
            action="call",
            capability="calculate_ndvi",
            arguments={"imagery_id": "94e758f38ede"},
            reason="ndvi",
        ),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_tools=("calculate_ndvi",)),
        user_id=user_id,
    )

    assert plan.tool_call is not None
    assert plan.tool_call.name == "calculate_ndvi"

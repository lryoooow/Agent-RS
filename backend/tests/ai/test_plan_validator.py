from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.agent.llm_planner import PlannerDecision
from app.agent.plan_validator import PlanValidator
from app.agent.routing import ALL_IMAGERY_TOOLS, AgentRoute
from app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _force_disk_fallback(monkeypatch):
    """锁死本组用例走"无 DB → 本地 metadata.json 兜底"路径。

    plan_validator 的 owner guard 经 validate_tool_access → user_owns_imagery，后者改为
    DB 优先 + 磁盘兜底。本组验证的是磁盘 owner 校验（用 tmp metadata.json）；把
    fetch_optional_pool 打成 async None，确保无论测试机 .env 是否 DATABASE_ENABLED=true
    都不连真库、稳定走兜底。DB 优先路径由 tests/agent/test_imagery_repo.py（PG 集成）覆盖。
    """
    async def _no_pool():
        return None

    monkeypatch.setattr("app.agent.imagery_access.fetch_optional_pool", _no_pool)


def reset_settings() -> None:
    get_settings.cache_clear()


def _owned_imagery(root: Path, imagery_id: str, owner_user_id: str) -> None:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    (imagery_dir / "metadata.json").write_text(
        json.dumps({"filename": "sample.tif", "owner_user_id": owner_user_id}),
        encoding="utf-8",
    )


VALID_IMAGERY_ARGS = {
    "calculate_ndvi": {"imagery_id": "94e758f38ede"},
    "raster_inspect": {"imagery_id": "94e758f38ede"},
    "calculate_spectral_index": {"imagery_id": "94e758f38ede", "index_type": "ndwi"},
    "render_band_composite": {"imagery_id": "94e758f38ede", "mode": "true_color"},
    "detect_objects": {"imagery_id": "94e758f38ede"},
    "segment_landcover": {"imagery_id": "94e758f38ede"},
    "cloud_shadow_mask": {"imagery_id": "94e758f38ede"},
    "extract_water_mask": {"imagery_id": "94e758f38ede"},
    "clip_reproject_raster": {"imagery_id": "94e758f38ede", "dst_crs": "EPSG:4326"},
    "ocr_recognize": {"imagery_id": "94e758f38ede"},
}


async def test_validator_accepts_web_search_agent(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    decision = PlannerDecision(
        action="call",
        capability="web_search",
        arguments={"query": "明天杭州天气", "reason": "需要实时天气"},
        reason="needs_current_weather",
    )

    plan = await PlanValidator().validate(
        decision,
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_agents=("web_search",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.agent_call is not None
    assert plan.agent_call.name == "web_search"


async def test_validator_rejects_unknown_capability() -> None:
    plan = await PlanValidator().validate(
        PlannerDecision(action="call", capability="missing", arguments={}, reason="bad"),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_agents=("web_search",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.action == "none"
    assert plan.validation_error == "unknown_capability"


async def test_validator_rejects_route_disallowed_capability(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    plan = await PlanValidator().validate(
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


async def test_validator_rejects_invalid_arguments(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_settings()
    plan = await PlanValidator().validate(
        PlannerDecision(action="call", capability="web_search", arguments={"query": ""}, reason="bad"),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_agents=("web_search",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.action == "none"
    assert "validation errors" in (plan.validation_error or "")


async def test_validator_rejects_other_user_imagery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_settings()
    _owned_imagery(tmp_path, "94e758f38ede", "other-user")

    plan = await PlanValidator().validate(
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


async def test_validator_rejects_other_user_for_every_imagery_tool(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_settings()
    _owned_imagery(tmp_path, "94e758f38ede", "other-user")

    assert set(VALID_IMAGERY_ARGS) == set(ALL_IMAGERY_TOOLS)
    for tool_name in ALL_IMAGERY_TOOLS:
        plan = await PlanValidator().validate(
            PlannerDecision(
                action="call",
                capability=tool_name,
                arguments=VALID_IMAGERY_ARGS[tool_name],
                reason="strict owner guard regression",
            ),
            route=AgentRoute(mode="full_pipeline", reason="test", candidate_tools=(tool_name,)),
            user_id=get_settings().default_user_id,
        )

        assert plan.action == "none", tool_name
        assert plan.validation_error == "imagery_not_found_or_forbidden", tool_name


async def test_validator_rejects_document_tool_without_owner_identity() -> None:
    plan = await PlanValidator().validate(
        PlannerDecision(
            action="call",
            capability="parse_document",
            arguments={"document_id": "11111111-1111-1111-1111-111111111111"},
            reason="document",
        ),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_tools=("parse_document",)),
        user_id=None,
    )

    assert plan.action == "none"
    assert plan.validation_error == "owner_required"


async def test_validator_rejects_unknown_argument_fields() -> None:
    plan = await PlanValidator().validate(
        PlannerDecision(
            action="call",
            capability="calculate_ndvi",
            arguments={"imagery_id": "94e758f38ede", "unexpected_field": "must fail"},
            reason="bad args",
        ),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_tools=("calculate_ndvi",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.action == "none"
    assert "Extra inputs are not permitted" in (plan.validation_error or "")


async def test_validator_accepts_generate_report_without_imagery_owner_guard() -> None:
    # 报告工具自成通道：被 route 候选放行，且不被影像/文档归属 guard 拦截
    # （归属由 build_conversation_report 内的对话校验保证）。无 imagery_id 也应通过。
    plan = await PlanValidator().validate(
        PlannerDecision(
            action="call",
            capability="generate_report",
            arguments={"reason": "用户请求生成报告"},
            reason="generate_report",
        ),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_tools=("generate_report",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.action == "call"
    assert plan.tool_call is not None
    assert plan.tool_call.name == "generate_report"
    assert plan.validation_error is None


async def test_validator_rejects_generate_report_outside_route() -> None:
    # 边界：generate_report 不在 route 候选里时仍按 route 白名单拒绝（与其它工具一致）。
    plan = await PlanValidator().validate(
        PlannerDecision(
            action="call",
            capability="generate_report",
            arguments={"reason": "x"},
            reason="generate_report",
        ),
        route=AgentRoute(mode="full_pipeline", reason="test", candidate_tools=("calculate_ndvi",)),
        user_id=get_settings().default_user_id,
    )

    assert plan.action == "none"
    assert plan.validation_error == "capability_not_allowed_by_route"


async def test_validator_accepts_owned_imagery_tool(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_settings()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)

    plan = await PlanValidator().validate(
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

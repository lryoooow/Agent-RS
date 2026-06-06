from __future__ import annotations

import json
from pathlib import Path

from app.agent.config import resolve_ai_config
from app.agent.intent_policy import IntentPolicy
from app.agent.search.cache import CachedDecision, get_decision_cache
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


def reset_state() -> None:
    get_settings.cache_clear()
    get_decision_cache().clear()


def _request(query: str, *, system_context: str | None = None) -> ChatRequest:
    messages = []
    if system_context:
        messages.append({"role": "system", "content": system_context})
    messages.append({"role": "user", "content": query})
    return ChatRequest(messages=messages)


def _owned_imagery(root: Path, imagery_id: str, owner_user_id: str) -> None:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    (imagery_dir / "metadata.json").write_text(
        json.dumps({"filename": "sample.tif", "owner_user_id": owner_user_id}),
        encoding="utf-8",
    )


def _decide(query: str, request: ChatRequest | None = None):
    request = request or _request(query)
    return IntentPolicy().decide(
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        config=resolve_ai_config(),
        web_search_available=True,
    )


def test_ndvi_decision_keeps_imagery_arguments(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)
    request = _request(
        "请计算 NDVI",
        system_context="当前上传影像：ID=94e758f38ede",
    )

    decision = _decide("请计算 NDVI", request)

    assert decision.capability_name == "calculate_ndvi"
    assert decision.capability_kind == "tool"
    assert decision.tool_call is not None
    assert decision.arguments["imagery_id"] == "94e758f38ede"


def test_spectral_index_decision_keeps_index_type(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)

    decision = _decide("计算 NDWI 94e758f38ede")

    assert decision.capability_name == "calculate_spectral_index"
    assert decision.arguments["imagery_id"] == "94e758f38ede"
    assert decision.arguments["index_type"] == "ndwi"


def test_composite_decision_keeps_mode(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)

    decision = _decide("显示 94e758f38ede 的假彩色")

    assert decision.capability_name == "render_band_composite"
    assert decision.arguments["mode"] == "false_color"


def test_raster_inspect_decision(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)

    decision = _decide("检查影像 94e758f38ede 的 CRS 和分辨率")

    assert decision.capability_name == "raster_inspect"
    assert decision.arguments["imagery_id"] == "94e758f38ede"


def test_ndvi_concept_question_skips_tool() -> None:
    reset_state()

    decision = _decide("什么是 NDVI？")

    assert decision.action == "skip"
    assert decision.tool_call is None


def test_ndvi_explanation_with_freshness_signal_uses_search() -> None:
    reset_state()

    decision = _decide("介绍一下 NDVI 的最新进展 2025")

    assert decision.capability_name == "web_search"
    assert decision.capability_kind == "agent"
    assert decision.trace_stage == "classifier_force"


def test_ndvi_explanation_with_freshness_signal_overrides_skip_pattern() -> None:
    reset_state()

    decision = _decide("解释一下这段 NDVI 最新政策")

    assert decision.capability_name == "web_search"
    assert decision.capability_kind == "agent"
    assert decision.trace_stage == "classifier_force"


def test_satellite_explanation_with_latest_official_parameters_uses_search() -> None:
    reset_state()

    decision = _decide("解释一下高分二号最新的官方参数")

    assert decision.capability_name == "web_search"
    assert decision.capability_kind == "agent"
    assert decision.trace_stage == "classifier_force"


def test_ndvi_policy_question_with_freshness_signal_uses_search() -> None:
    reset_state()

    decision = _decide("什么是 NDVI 最新政策")

    assert decision.capability_name == "web_search"
    assert decision.capability_kind == "agent"
    assert decision.trace_stage == "classifier_force"


def test_force_search_decision() -> None:
    reset_state()

    decision = _decide("查一下今天高分二号有什么最新新闻")

    assert decision.capability_name == "web_search"
    assert decision.capability_kind == "agent"
    assert decision.agent_call is not None
    assert decision.trace_stage == "classifier_force"


def test_weather_forecast_forces_search() -> None:
    reset_state()

    decision = _decide("明天杭州天气预报")

    assert decision.capability_name == "web_search"
    assert decision.capability_kind == "agent"
    assert decision.agent_call is not None
    assert decision.trace_stage == "classifier_force"


def test_weather_rain_level_question_forces_search() -> None:
    reset_state()

    decision = _decide("明天杭州有中雨吗？")

    assert decision.capability_name == "web_search"
    assert decision.capability_kind == "agent"
    assert decision.agent_call is not None
    assert decision.trace_stage == "classifier_force"


def test_code_with_year_does_not_force_search() -> None:
    reset_state()

    decision = _decide("帮我写一个 2024 年数据处理脚本")

    assert decision.capability_name != "web_search"
    assert decision.action == "skip"


def test_uncertain_search_returns_ask_planner() -> None:
    reset_state()

    decision = _decide("Transformer 注意力机制的实际应用边界")

    assert decision.action == "ask_planner"
    assert decision.agent_call is None


def test_search_cache_hit_returns_agent_call() -> None:
    reset_state()
    query = "Transformer 注意力机制的实际应用边界"
    request = _request(query)
    config = resolve_ai_config()
    scope = "|".join(
        [
            get_settings().default_user_id,
            request.conversation_id or "no-conversation",
            config.model,
            "web:on",
            f"rag:{int(request.use_rag)}",
            f"memory:{int(request.use_memory)}",
        ]
    )
    get_decision_cache().put_decision(query, CachedDecision.SEARCH, scope=scope)

    decision = IntentPolicy().decide(
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        config=config,
        web_search_available=True,
    )

    assert decision.agent_call is not None
    assert decision.trace_stage == "cache_hit_search"


def test_no_search_cache_hit_skips() -> None:
    reset_state()
    query = "Transformer 注意力机制的实际应用边界"
    request = _request(query)
    config = resolve_ai_config()
    scope = "|".join(
        [
            get_settings().default_user_id,
            request.conversation_id or "no-conversation",
            config.model,
            "web:on",
            f"rag:{int(request.use_rag)}",
            f"memory:{int(request.use_memory)}",
        ]
    )
    get_decision_cache().put_decision(query, CachedDecision.NO_SEARCH, scope=scope)

    decision = IntentPolicy().decide(
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        config=config,
        web_search_available=True,
    )

    assert decision.action == "skip"
    assert decision.trace_stage == "cache_hit_skip"

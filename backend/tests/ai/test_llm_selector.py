from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.config import ResolvedAIConfig
from app.agent.llm_planner import capability_snapshot
from app.agent.routing import ALL_CANDIDATE_TOOLS, build_agent_route
from app.agent.search.cache import get_planner_decision_cache
from app.agent.tool_selector import TaskSelector
from app.agent.types import AgentTrace
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


class FakeCompletions:
    def __init__(self, content: str):
        self.content = content
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


class FakeClient:
    def __init__(self, completions: FakeCompletions):
        self.chat = SimpleNamespace(completions=completions)


async def _add_event(trace, _on_event, stage, label, **metadata):
    return trace.add(stage, label, **metadata)


def reset_state() -> None:
    get_settings.cache_clear()
    get_planner_decision_cache().clear()


def _config() -> ResolvedAIConfig:
    return ResolvedAIConfig(
        provider="openai-compatible",
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        timeout_seconds=60,
        max_retries=0,
        trust_env_proxy=False,
    )


def _request(query: str) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": query}])


def _owned_imagery(root: Path, imagery_id: str, owner_user_id: str) -> None:
    imagery_dir = root / imagery_id
    imagery_dir.mkdir(parents=True)
    (imagery_dir / "metadata.json").write_text(
        json.dumps({"filename": "sample.tif", "owner_user_id": owner_user_id}),
        encoding="utf-8",
    )


def test_non_empty_question_routes_to_llm_pipeline_by_default() -> None:
    reset_state()

    route = build_agent_route("帮我写一个排序函数", _request("帮我写一个排序函数"))

    assert route.mode == "full_pipeline"
    assert route.reason == "llm_planner_route"
    assert route.candidate_agents == ("web_search",)
    assert route.candidate_tools == ALL_CANDIDATE_TOOLS


@pytest.mark.asyncio
async def test_selector_returns_none_when_planner_says_no_call(monkeypatch) -> None:
    reset_state()
    query = "帮我写一个排序函数"
    request = _request(query)
    route = build_agent_route(query, request)
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(FakeCompletions('{"action":"none","capability":null,"arguments":{},"reason":"direct"}')),
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert selection.agent_call is None
    assert selection.tool_call is None
    assert [event.stage for event in trace.events] == [
        "planner_started",
        "planner_completed",
        "planner_no_call",
    ]


@pytest.mark.asyncio
async def test_selector_uses_planner_for_web_search(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "这件事是否需要外部核实"
    request = _request(query)
    route = build_agent_route(query, request)
    completions = FakeCompletions(
        '{"action":"call","capability":"web_search","arguments":{"query":"这件事是否需要外部核实","reason":"需要外部验证"},"reason":"external_check"}'
    )
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(completions),
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert selection.agent_call is not None
    assert selection.agent_call.name == "web_search"
    assert [event.stage for event in trace.events] == [
        "planner_started",
        "planner_completed",
        "planner_selected",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("index_type", "query"),
    [
        ("ndwi", "计算影像的 NDWI"),
        ("mndwi", "计算影像的 MNDWI"),
        ("savi", "计算影像的 SAVI"),
        ("msavi", "计算影像的 MSAVI"),
        ("gndvi", "计算影像的 GNDVI"),
        ("ndmi", "计算影像的 NDMI"),
        ("nbr", "计算影像的 NBR"),
        ("bsi", "计算影像的 BSI"),
    ],
)
async def test_selector_accepts_all_spectral_index_plans(monkeypatch, tmp_path: Path, index_type: str, query: str) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    user_id = get_settings().default_user_id
    _owned_imagery(tmp_path, "94e758f38ede", user_id)
    request = _request(query)
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(
            FakeCompletions(
                json.dumps(
                    {
                        "action": "call",
                        "capability": "calculate_spectral_index",
                        "arguments": {"imagery_id": "94e758f38ede", "index_type": index_type},
                        "reason": "spectral_index",
                    }
                )
            )
        ),
        config=_config(),
        request=request,
        query=query,
        user_id=user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=build_agent_route(query, request),
    )

    assert selection.tool_call is not None
    assert selection.tool_call.name == "calculate_spectral_index"
    assert selection.tool_call.arguments["index_type"] == index_type


@pytest.mark.asyncio
async def test_selector_rejects_invalid_plan_without_caching(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "这件事是否需要外部核实"
    request = _request(query)
    route = build_agent_route(query, request)
    trace = AgentTrace(enabled=True)
    first = FakeCompletions('{"action":"call","capability":"missing","arguments":{},"reason":"bad"}')

    selection = await TaskSelector().select(
        client=FakeClient(first),
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert selection.agent_call is None
    assert selection.tool_call is None
    assert selection.planner_error_context
    assert trace.events[-1].stage == "plan_validation_failed"

    second = FakeCompletions(
        '{"action":"call","capability":"web_search","arguments":{"query":"ok","reason":"retry"},"reason":"external_check"}'
    )
    second_selection = await TaskSelector().select(
        client=FakeClient(second),
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
        route=route,
    )
    assert second_selection.agent_call is not None
    assert second.calls


@pytest.mark.asyncio
async def test_selector_uses_validated_cache(monkeypatch) -> None:
    monkeypatch.setenv("TAVILY_API_KEY", "test")
    reset_state()
    query = "这件事是否需要外部核实"
    request = _request(query)
    route = build_agent_route(query, request)
    first = FakeCompletions(
        '{"action":"call","capability":"web_search","arguments":{"query":"这件事是否需要外部核实","reason":"需要外部验证"},"reason":"external_check"}'
    )

    first_selection = await TaskSelector().select(
        client=FakeClient(first),
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
        route=route,
    )
    assert first_selection.agent_call is not None

    second = FakeCompletions('{"action":"none","capability":null,"arguments":{},"reason":"wrong"}')
    trace = AgentTrace(enabled=True)
    second_selection = await TaskSelector().select(
        client=FakeClient(second),
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert second_selection.agent_call is not None
    assert second.calls == []
    assert trace.events[-1].metadata["cached"] is True


# ───────────────────────── 缓存 scope 上下文一致性（根因回归）─────────────────────────
# 背景：规划器决策依赖「影像清单」与「本对话分析状态」（见 llm_planner._build_messages），
# 但缓存 scope 曾遗漏这两维 → 同 query 不同上下文错误命中同一决策（跨影像误判 / 报告状态钉死）。
# 下列用例锁住「上下文变 → scope 变 → 不命中」，与既有 test_selector_uses_validated_cache
# （上下文不变 → 命中）形成正反两面闭环。


def _request_in_conversation(query: str, conversation_id: str) -> ChatRequest:
    return ChatRequest(
        messages=[{"role": "user", "content": query}],
        conversation_id=conversation_id,
    )


@pytest.mark.asyncio
async def test_cache_misses_when_imagery_inventory_changes(monkeypatch, tmp_path: Path) -> None:
    # bug #1 回归：同 user/conversation/query，影像清单变化时决策缓存必须失效，
    # 否则会对「换图前」的旧影像执行（跨影像误判）。
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    user_id = get_settings().default_user_id
    query = "计算这张影像的 NDVI"
    conversation_id = "11111111-1111-4111-8111-111111111111"
    request = _request_in_conversation(query, conversation_id)
    route = build_agent_route(query, request)

    # 第一轮：清单只有影像 A → 规划并入缓存（走 planner 一次）。
    _owned_imagery(tmp_path, "94e758f38ede", user_id)
    first = FakeCompletions(
        '{"action":"call","capability":"calculate_ndvi","arguments":{"imagery_id":"94e758f38ede"},"reason":"ndvi"}'
    )
    first_selection = await TaskSelector().select(
        client=FakeClient(first),
        config=_config(),
        request=request,
        query=query,
        user_id=user_id,
        trace=AgentTrace(enabled=True),
        on_event=None,
        add_event=_add_event,
        route=route,
    )
    assert first_selection.tool_call is not None
    assert first.calls  # 第一次确实调用了 planner

    # 第二轮：清单新增影像 B（指纹变化）→ 同 query 不应命中第一轮缓存，必须重新规划。
    _owned_imagery(tmp_path, "8d3f00aa1122", user_id)
    second = FakeCompletions(
        '{"action":"call","capability":"calculate_ndvi","arguments":{"imagery_id":"8d3f00aa1122"},"reason":"ndvi"}'
    )
    trace = AgentTrace(enabled=True)
    second_selection = await TaskSelector().select(
        client=FakeClient(second),
        config=_config(),
        request=request,
        query=query,
        user_id=user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )
    assert second_selection.tool_call is not None
    assert second.calls  # 关键：清单变化 → 缓存未命中 → planner 被再次调用
    assert trace.events[-1].metadata.get("cached") is not True


@pytest.mark.asyncio
async def test_planner_cache_scope_includes_imagery_document_and_analysis(monkeypatch, tmp_path: Path) -> None:
    # 纯单元：验证动态证据维度都进入 scope，任一变化都应使规划缓存失效。
    from app.agent import tool_selector

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    user_id = get_settings().default_user_id
    query = "计算这张影像的 NDVI"
    request = _request_in_conversation(query, "22222222-2222-4222-8222-222222222222")
    route = build_agent_route(query, request)
    capabilities = capability_snapshot()

    async def _scope() -> str:
        return await tool_selector._planner_cache_scope(
            config=_config(),
            route=route,
            capabilities=capabilities,
            user_id=user_id,
            request=request,
        )

    # 基线：无影像、分析状态打桩为 "0"。
    monkeypatch.setattr(tool_selector, "_analysis_state_fingerprint", _stub_async("0"))
    monkeypatch.setattr(tool_selector, "_document_fingerprint", _stub_async("none"))
    base = await _scope()
    assert "img:none" in base
    assert "doc:none" in base
    assert "ana:0" in base

    # 影像清单变化 → scope 变。
    _owned_imagery(tmp_path, "94e758f38ede", user_id)
    with_imagery = await _scope()
    assert with_imagery != base
    assert "img:none" not in with_imagery

    monkeypatch.setattr(tool_selector, "_document_fingerprint", _stub_async("document-fp"))
    with_document = await _scope()
    assert with_document != with_imagery
    assert "doc:document-fp" in with_document

    # 分析状态 0→1 → scope 变。
    monkeypatch.setattr(tool_selector, "_analysis_state_fingerprint", _stub_async("1"))
    with_analysis = await _scope()
    assert with_analysis != with_document
    assert "ana:1" in with_analysis


def _stub_async(value: str):
    async def _inner(*_args, **_kwargs) -> str:
        return value
    return _inner


@pytest.mark.asyncio
async def test_selector_emits_guard_stage_for_forbidden_imagery(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    reset_state()
    _owned_imagery(tmp_path, "94e758f38ede", "other-user")
    query = "计算这张影像的 NDVI"
    request = _request(query)
    route = build_agent_route(query, request)
    trace = AgentTrace(enabled=True)

    selection = await TaskSelector().select(
        client=FakeClient(
            FakeCompletions(
                '{"action":"call","capability":"calculate_ndvi","arguments":{"imagery_id":"94e758f38ede"},"reason":"ndvi"}'
            )
        ),
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert selection.tool_call is None
    assert selection.planner_error_context
    assert trace.events[-1].stage == "capability_guard_rejected"
    assert trace.events[-1].metadata["error"] == "imagery_not_found_or_forbidden"


@pytest.mark.asyncio
async def test_selector_emits_guard_stage_for_forbidden_document(monkeypatch) -> None:
    reset_state()
    query = "总结文档 11111111-1111-1111-1111-111111111111"
    request = _request(query)
    route = build_agent_route(query, request)
    trace = AgentTrace(enabled=True)

    async def reject_document(*_args, **_kwargs):
        return "document_not_found_or_forbidden"

    monkeypatch.setattr(
        "app.agent.plan_validator.validate_tool_access",
        reject_document,
    )

    selection = await TaskSelector().select(
        client=FakeClient(
            FakeCompletions(
                '{"action":"call","capability":"parse_document","arguments":{"document_id":"11111111-1111-1111-1111-111111111111"},"reason":"summary"}'
            )
        ),
        config=_config(),
        request=request,
        query=query,
        user_id=get_settings().default_user_id,
        trace=trace,
        on_event=None,
        add_event=_add_event,
        route=route,
    )

    assert selection.tool_call is None
    assert selection.planner_error_context
    assert trace.events[-1].stage == "capability_guard_rejected"
    assert trace.events[-1].metadata["error"] == "document_not_found_or_forbidden"

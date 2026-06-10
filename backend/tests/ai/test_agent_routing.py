from __future__ import annotations

from app.agent.routing import (
    ALL_CANDIDATE_TOOLS,
    ALL_DOCUMENT_TOOLS,
    ALL_IMAGERY_TOOLS,
    build_agent_route,
)
from app.schemas.chat import ChatRequest


def _request(query: str) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": query}], use_memory=False, use_rag=False)


def test_non_empty_requests_enter_llm_planner_pipeline() -> None:
    route = build_agent_route("帮我写一个排序函数", _request("帮我写一个排序函数"))

    assert route.mode == "full_pipeline"
    assert route.reason == "llm_planner_route"
    assert route.candidate_tools == ALL_CANDIDATE_TOOLS
    assert route.candidate_agents == ("web_search",)
    assert route.skip_retrieval is False


def test_candidate_tools_span_both_channels() -> None:
    """全流程路由的候选工具应同时覆盖影像通道与文档通道。"""
    route = build_agent_route("总结这篇文档", _request("总结这篇文档"))

    for tool in ALL_IMAGERY_TOOLS:
        assert tool in route.candidate_tools
    for tool in ALL_DOCUMENT_TOOLS:
        assert tool in route.candidate_tools
    # parse_document 在候选集里（否则会被 plan_validator 拦截）
    assert "parse_document" in route.candidate_tools


def test_empty_query_keeps_direct_route_and_skips_retrieval() -> None:
    route = build_agent_route("   ", _request("x"))

    assert route.mode == "direct_chat"
    assert route.reason == "empty_query"
    assert route.skip_retrieval is True

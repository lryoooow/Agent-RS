from __future__ import annotations

import pytest

from app.agent.routing import ALL_IMAGERY_TOOLS, build_agent_route
from app.schemas.chat import ChatRequest


def _request(query: str) -> ChatRequest:
    return ChatRequest(messages=[{"role": "user", "content": query}], use_memory=False, use_rag=False)


@pytest.mark.parametrize("query", ["检查影像", "计算 NDWI", "假彩色显示"])
def test_imagery_tools_override_direct_route(query: str) -> None:
    route = build_agent_route(query, _request(query))

    assert route.mode == "full_pipeline"
    assert route.reason == "imagery_tool_override"
    assert route.candidate_tools == ALL_IMAGERY_TOOLS

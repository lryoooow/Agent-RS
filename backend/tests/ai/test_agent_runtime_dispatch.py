import pytest

import app.agent.runtime as runtime_module
from app.agent.runtime import AgentRuntime
from app.agent.types import AgentTrace, RuntimeToolCall, ToolRunResult


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_domain"),
    [
        ("calculate_ndvi", {"imagery_id": "94e758f38ede"}, "spectral_agent"),
        ("extract_water_mask", {"imagery_id": "94e758f38ede"}, "preprocess_agent"),
        (
            "parse_document",
            {"document_id": "11111111-1111-1111-1111-111111111111"},
            "document_agent",
        ),
        ("ocr_recognize", {"imagery_id": "94e758f38ede"}, "document_agent"),
    ],
)
async def test_runtime_dispatches_tool_calls_to_domain_agents(
    monkeypatch,
    tool_name: str,
    arguments: dict,
    expected_domain: str,
) -> None:
    seen: list[str] = []

    class _StubDomainAgent:
        def __init__(self, domain_name: str) -> None:
            seen.append(domain_name)

        async def run(self, tool_call, *, user_id, trace, on_event=None):
            assert tool_call.name == tool_name
            return ToolRunResult(tool_context=f"{seen[-1]} ok")

    monkeypatch.setattr(runtime_module, "DomainToolAgent", _StubDomainAgent)

    result = await AgentRuntime().run_tool_call(
        RuntimeToolCall(name=tool_name, arguments=arguments),
        trace=AgentTrace(enabled=True),
        user_id="u1",
    )

    assert seen == [expected_domain]
    assert result.tool_context == f"{expected_domain} ok"

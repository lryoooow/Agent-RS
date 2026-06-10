from types import SimpleNamespace

import pytest

import app.agent.runtime as runtime_module
from app.agent.runtime import AgentRuntime
from app.agent.types import AgentTrace, RuntimeToolCall, ToolRunResult
from app.agent.config import resolve_ai_config
from app.agent.request_builder import build_provider_request_context
from app.schemas.chat import ChatRequest
from app.core.settings import get_settings


def reset_settings() -> None:
    get_settings.cache_clear()


def response_with_content(content: str):
    return SimpleNamespace(
        model="test-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            )
        ],
        usage=None,
    )


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, completions):
        self.chat = FakeChat(completions)


@pytest.mark.asyncio
async def test_agent_runtime_direct_answer_when_planner_returns_none(monkeypatch):
    class Completions:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("stream") is False and kwargs.get("max_tokens"):
                return response_with_content(
                    '{"action":"none","capability":null,"arguments":{},"reason":"direct"}'
                )
            return response_with_content("direct")

    monkeypatch.setenv("AI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", "test-model")
    reset_settings()

    request = ChatRequest(messages=[{"role": "user", "content": "hello"}])
    context = await build_provider_request_context(request)
    completions = Completions()
    result = await AgentRuntime().complete(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=request,
        initial_context=context,
        user_id=get_settings().default_user_id,
    )

    assert result.response.choices[0].message.content == "direct"
    assert all("tools" not in call for call in completions.calls)
    trace = result.trace.model_dump()
    assert [event["stage"] for event in trace["events"]] == [
        "context_assembled",
        "planner_started",
        "planner_completed",
        "planner_no_call",
    ]


@pytest.mark.asyncio
async def test_agent_runtime_uses_search_agent_and_injects_context(monkeypatch):
    class Completions:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("stream") is False and kwargs.get("max_tokens"):
                return response_with_content(
                    '{"action":"call","capability":"web_search","arguments":{"query":"latest python","reason":"fresh"},"reason":"needs_search"}'
                )
            assert any("tool answer" in message["content"] for message in kwargs["messages"])
            return response_with_content("final answer")

    async def fake_run_web_search(args):
        return ToolRunResult(
            tool_context="tool answer",
            result_count=1,
            query=args.query,
        )

    monkeypatch.setenv("AI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", "test-model")
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    reset_settings()

    monkeypatch.setattr("app.agent.search_agent.run_web_search", fake_run_web_search)

    request = ChatRequest(messages=[{"role": "user", "content": "what is latest python"}])
    context = await build_provider_request_context(request)
    reused_retrieved_context = []
    original_build_context = runtime_module.build_provider_request_context

    async def wrapped_build_context(*args, **kwargs):
        reused_retrieved_context.append(kwargs.get("retrieved_context") is context.retrieved_context)
        return await original_build_context(*args, **kwargs)

    monkeypatch.setattr(runtime_module, "build_provider_request_context", wrapped_build_context)
    completions = Completions()
    result = await AgentRuntime().complete(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=request,
        initial_context=context,
        user_id=get_settings().default_user_id,
    )

    assert result.response.choices[0].message.content == "final answer"
    assert result.used_capability is True
    assert result.used_tool is False
    assert result.dispatch_kind == "agent"
    assert reused_retrieved_context == [True]
    trace = result.trace.model_dump()
    assert [event["stage"] for event in trace["events"]] == [
        "context_assembled",
        "planner_started",
        "planner_completed",
        "planner_selected",
        "tool_requested",
        "child_agent_running",
        "tool_execution_started",
        "tool_execution_completed",
        "tool_context_ready",
        "final_answering",
    ]
    assert trace["events"][4]["metadata"]["execution_kind"] == "agent"
    assert trace["events"][-1]["metadata"]["dispatch_kind"] == "agent"


@pytest.mark.asyncio
async def test_agent_runtime_rejects_invalid_tool_arguments(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    reset_settings()

    result = await AgentRuntime().run_tool_call(
        RuntimeToolCall(name="calculate_ndvi", arguments={"imagery_id": ""}),
        trace=AgentTrace(enabled=True),
    )

    assert result.error
    assert "参数" in result.tool_context

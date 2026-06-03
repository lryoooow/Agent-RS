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


def test_ndvi_concept_question_does_not_create_tool_call():
    assert runtime_module._detect_ndvi_intent("什么是 NDVI？") is None


def test_ndvi_calculation_requires_explicit_imagery_id():
    assert runtime_module._detect_ndvi_intent("帮我计算 NDVI") is None


def test_ndvi_calculation_with_imagery_id_creates_tool_call():
    request = ChatRequest(
        messages=[
            {"role": "system", "content": "当前上传影像：ID=94e758f38ede，图层类型=preview。"},
            {"role": "user", "content": "请计算 NDVI"},
        ]
    )

    tool_call = runtime_module._detect_ndvi_intent("请计算 NDVI", request.messages)

    assert tool_call is not None
    assert tool_call.name == "calculate_ndvi"
    assert tool_call.arguments["imagery_id"] == "94e758f38ede"


def test_ndvi_calculation_ignores_random_hex_without_uploaded_context():
    assert runtime_module._detect_ndvi_intent("请计算 abcdef123456 的 NDVI") is None


def test_ndvi_calculation_uses_recent_imagery_context():
    request = ChatRequest(
        messages=[
            {
                "role": "system",
                "content": "当前上传影像：ID=d54d9f9373c7，图层类型=preview。",
            },
            {"role": "user", "content": "计算NDVI"},
        ]
    )

    tool_call = runtime_module._detect_ndvi_intent("计算NDVI", request.messages)

    assert tool_call is not None
    assert tool_call.name == "calculate_ndvi"
    assert tool_call.arguments["imagery_id"] == "d54d9f9373c7"


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, completions):
        self.chat = FakeChat(completions)


@pytest.mark.asyncio
async def test_agent_runtime_does_not_pass_tools_when_search_disabled(monkeypatch):
    class Completions:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            return response_with_content("direct")

    monkeypatch.setenv("AI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", "test-model")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    reset_settings()

    request = ChatRequest(messages=[{"role": "user", "content": "hello"}])
    context = await build_provider_request_context(request)
    completions = Completions()
    result = await AgentRuntime().complete(
        client=FakeClient(completions),
        config=resolve_ai_config(),
        request=request,
        initial_context=context,
        user_id=None,
    )

    assert result.response.choices[0].message.content == "direct"
    assert "tools" not in completions.calls[0]
    trace = result.trace.model_dump()
    assert trace["enabled"] is True
    assert [event["stage"] for event in trace["events"]] == ["context_assembled", "classifier_skip"]


@pytest.mark.asyncio
async def test_agent_runtime_uses_tool_call_and_injects_tool_context(monkeypatch):
    class Completions:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
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
    from app.agent.tool_registry import RegisteredTool
    from app.agent.tools.web_search.schema import WEB_SEARCH_TOOL, WebSearchArguments

    monkeypatch.setattr(
        "app.agent.tool_registry.TOOLS",
        {
            "web_search": RegisteredTool(
                name="web_search",
                definition=WEB_SEARCH_TOOL,
                argument_model=WebSearchArguments,
                runner=fake_run_web_search,
            )
        },
    )

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
        user_id=None,
    )

    assert result.response.choices[0].message.content == "final answer"
    assert len(completions.calls) == 1
    assert "tools" not in completions.calls[0]
    assert reused_retrieved_context == [True]
    trace = result.trace.model_dump()
    assert trace["enabled"] is True
    assert [event["stage"] for event in trace["events"]] == [
        "context_assembled",
        "classifier_force",
        "tool_requested",
        "child_agent_running",
        "tool_execution_started",
        "tool_execution_completed",
        "tool_context_ready",
        "final_answering",
    ]



@pytest.mark.asyncio
async def test_agent_runtime_rejects_invalid_tool_arguments(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    reset_settings()

    result = await AgentRuntime().run_tool_call(
        RuntimeToolCall(name="web_search", arguments={"query": "", "reason": "fresh"}),
        trace=AgentTrace(enabled=True),
    )

    assert result.error
    assert "工具参数无效" in result.tool_context

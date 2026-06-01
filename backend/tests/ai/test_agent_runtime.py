from types import SimpleNamespace

import pytest
from openai.types.chat import ChatCompletion, ChatCompletionMessage
from openai.types.chat.chat_completion import Choice
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageToolCall,
    Function,
)

import app.lib.ai.agents.runtime as runtime_module
from app.lib.ai.agents.runtime import AgentRuntime
from app.lib.ai.agents.types import AgentTrace, RuntimeToolCall, ToolRunResult
from app.lib.ai.config import resolve_ai_config
from app.lib.ai.request_builder import build_provider_request_context
from app.schemas.chat import ChatRequest
from app.shared.settings import get_settings


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


def response_with_tool_call(arguments: str):
    return SimpleNamespace(
        model="test-model",
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call-1",
                            function=SimpleNamespace(name="web_search", arguments=arguments),
                        )
                    ],
                ),
                finish_reason="tool_calls",
            )
        ],
        usage=None,
    )


def sdk_response_with_tool_call(arguments: str) -> ChatCompletion:
    return ChatCompletion(
        id="chatcmpl-test",
        created=0,
        model="test-model",
        object="chat.completion",
        choices=[
            Choice(
                finish_reason="tool_calls",
                index=0,
                message=ChatCompletionMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        ChatCompletionMessageToolCall(
                            id="call-sdk",
                            type="function",
                            function=Function(name="web_search", arguments=arguments),
                        )
                    ],
                ),
            )
        ],
    )


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, completions):
        self.chat = FakeChat(completions)


def test_first_tool_call_parses_openai_sdk_response_object():
    response = sdk_response_with_tool_call(
        '{"query": "qwen tools", "reason": "verify sdk structure"}'
    )

    tool_call = AgentRuntime()._first_tool_call(response)

    assert tool_call is not None
    assert tool_call.name == "web_search"
    assert tool_call.call_id == "call-sdk"
    assert tool_call.arguments == {
        "query": "qwen tools",
        "reason": "verify sdk structure",
    }


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
    assert result.trace.model_dump() == {"enabled": False, "events": []}


@pytest.mark.asyncio
async def test_agent_runtime_uses_tool_call_and_injects_tool_context(monkeypatch):
    class Completions:
        def __init__(self):
            self.calls = []

        async def create(self, **kwargs):
            self.calls.append(kwargs)
            assert any("tool answer" in message["content"] for message in kwargs["messages"])
            return response_with_content("final answer")

    async def fake_run_web_search(args, request):
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
    from app.lib.ai.agents.tool_registry import RegisteredTool
    from app.lib.ai.agents.tools.web_search.schema import WEB_SEARCH_TOOL, WebSearchArguments

    monkeypatch.setattr(
        "app.lib.ai.agents.tool_registry.TOOLS",
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
        "classifier_force",
        "tool_requested",
        "child_agent_running",
        "tool_context_ready",
        "final_answering",
    ]



@pytest.mark.asyncio
async def test_agent_runtime_rejects_invalid_tool_arguments(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    reset_settings()

    result = await AgentRuntime().run_tool_call(
        RuntimeToolCall(name="web_search", arguments={"query": "", "reason": "fresh"}),
        request=ChatRequest(messages=[{"role": "user", "content": "latest news"}]),
        trace=AgentTrace(enabled=True),
    )

    assert result.error
    assert "联网搜索参数无效" in result.tool_context

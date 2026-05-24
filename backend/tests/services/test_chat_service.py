from types import SimpleNamespace

import pytest

from app.schemas.chat import ChatRequest, ProviderConfig
from app.services.chat_service import ChatService
from app.shared.settings import get_settings


class FakeCompletions:
    async def create(self, **kwargs):
        assert kwargs["model"] == "client-model"
        if kwargs["stream"] is True:
            return fake_stream()
        assert kwargs["messages"][0]["role"] == "system"
        return SimpleNamespace(
            model="client-model",
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="answer"),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        )


class FakeChat:
    completions = FakeCompletions()


class FakeClient:
    chat = FakeChat()


async def fake_stream():
    yield SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content="stream"),
                finish_reason="stop",
            )
        ],
        usage=None,
    )


@pytest.mark.asyncio
async def test_chat_service_uses_ai_service_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("ALLOW_CLIENT_PROVIDER_CONFIG", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.lib.ai.ai_service.create_chat_client", lambda _: FakeClient())

    service = ChatService()
    request = ChatRequest(
        messages=[{"role": "user", "content": "hello"}],
        system_prompt="be short",
        provider_config=ProviderConfig(
            base_url="https://client.example/v1",
            api_key="client-key",
            model="client-model",
        ),
    )

    response = await service.chat(request)

    assert response.content == "answer"
    assert response.model == "client-model"
    assert response.usage
    assert response.usage.total_tokens == 3


@pytest.mark.asyncio
async def test_chat_service_streams_sse_events(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("ALLOW_CLIENT_PROVIDER_CONFIG", "true")
    get_settings.cache_clear()
    monkeypatch.setattr("app.lib.ai.ai_service.create_chat_client", lambda _: FakeClient())

    service = ChatService()
    request = ChatRequest(
        messages=[{"role": "user", "content": "hello"}],
        provider_config=ProviderConfig(
            base_url="https://client.example/v1",
            api_key="client-key",
            model="client-model",
        ),
    )

    events = [event async for event in service.stream_chat(request)]

    assert events[0] == 'event: meta\ndata: {"model": "client-model", "provider": "openai-compatible"}\n\n'
    assert events[1] == 'event: analysis_status\ndata: {"status": "analyzing", "label": "正在分析问题…"}\n\n'
    assert events[2] == 'event: analysis_status\ndata: {"status": "preparing", "label": "正在整理内容…"}\n\n'
    assert events[3] == 'event: analysis_status\ndata: {"status": "answering", "label": "正在组织回复…"}\n\n'
    assert events[4] == 'event: analysis_status\ndata: {"status": "complete", "label": "思考完成"}\n\n'
    assert events[5] == 'event: delta\ndata: {"content": "stream"}\n\n'
    assert events[6] == 'event: done\ndata: {"finish_reason": "stop"}\n\n'

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.agent.persistence import PersistenceContext
from app.schemas.chat import ChatRequest, ProviderConfig
from app.services.chat_service import ChatService
from app.core.settings import get_settings


class FakeCompletions:
    async def create(self, **kwargs):
        assert kwargs["model"] == "client-model"
        if kwargs.get("max_tokens"):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"none","capability":null,"arguments":{},"reason":"direct"}'
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )
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


class FailingStreamCompletions:
    async def create(self, **kwargs):
        if kwargs.get("max_tokens"):
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"none","capability":null,"arguments":{},"reason":"direct"}'
                        ),
                        finish_reason="stop",
                    )
                ],
                usage=None,
            )
        raise RuntimeError("provider unavailable")


class FailingStreamChat:
    completions = FailingStreamCompletions()


class FailingStreamClient:
    chat = FailingStreamChat()


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


def _event_data(event: str, event_name: str) -> dict:
    prefix = f"event: {event_name}\ndata: "
    assert event.startswith(prefix)
    assert event.endswith("\n\n")
    return json.loads(event[len(prefix):-2])


def _assert_meta_event(event: str, *, require_persistence_ids: bool) -> dict:
    meta = _event_data(event, "meta")
    assert meta["model"] == "client-model"
    assert meta["provider"] == "openai-compatible"

    persistence_keys = ("conversation_id", "user_message_id", "assistant_message_id")
    if require_persistence_ids:
        for key in persistence_keys:
            assert isinstance(meta[key], str)
            UUID(meta[key])
    else:
        for key in persistence_keys:
            if key in meta:
                assert isinstance(meta[key], str)
                UUID(meta[key])
    return meta


def _assert_rag_trace_baseline(done_payload: dict) -> None:
    rag_trace = done_payload["rag_trace"]
    assert rag_trace["use_rag"] is False
    assert rag_trace["use_memory"] is True


@pytest.fixture(autouse=True)
def deterministic_chat_service_environment(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_service_uses_ai_service_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("ALLOW_CLIENT_PROVIDER_CONFIG", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr("app.agent.ai_service.create_chat_client", lambda _: FakeClient())

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
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr("app.agent.ai_service.create_chat_client", lambda _: FakeClient())

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

    _assert_meta_event(events[0], require_persistence_ids=False)
    assert events[1] == 'event: analysis_status\ndata: {"status": "analyzing", "label": "正在解析问题…"}\n\n'
    assert events[2].startswith("event: agent_status\n")
    assert '"status": "context_assembled"' in events[2]
    assert events[3].startswith("event: agent_status\n")
    assert '"status": "planner_started"' in events[3]
    assert events[4].startswith("event: agent_status\n")
    assert '"status": "planner_completed"' in events[4]
    assert events[5].startswith("event: agent_status\n")
    assert '"status": "planner_no_call"' in events[5]
    assert events[6] == 'event: analysis_status\ndata: {"status": "preparing", "label": "正在整理内容…"}\n\n'
    assert events[7] == 'event: analysis_status\ndata: {"status": "answering", "label": "正在组织回复…"}\n\n'
    assert events[8] == 'event: analysis_status\ndata: {"status": "complete", "label": "思考完成"}\n\n'
    assert events[9] == 'event: delta\ndata: {"content": "stream"}\n\n'
    done = json.loads(events[10].split("data: ", 1)[1])
    assert done["finish_reason"] == "stop"
    assert done["retrieved_chunks"] == 0
    _assert_rag_trace_baseline(done)
    assert [event["stage"] for event in done["agent_trace"]["events"]] == [
        "context_assembled",
        "planner_started",
        "planner_completed",
        "planner_no_call",
    ]


@pytest.mark.asyncio
async def test_chat_service_streams_initial_status_before_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("ALLOW_CLIENT_PROVIDER_CONFIG", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr("app.agent.ai_service.create_chat_client", lambda _: FailingStreamClient())

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

    _assert_meta_event(events[0], require_persistence_ids=False)
    assert events[1] == 'event: analysis_status\ndata: {"status": "analyzing", "label": "正在解析问题…"}\n\n'
    assert events[2].startswith("event: agent_status\n")
    assert '"status": "context_assembled"' in events[2]
    assert events[3].startswith("event: agent_status\n")
    assert '"status": "planner_started"' in events[3]
    assert events[4].startswith("event: agent_status\n")
    assert '"status": "planner_completed"' in events[4]
    assert events[5].startswith("event: agent_status\n")
    assert '"status": "planner_no_call"' in events[5]
    assert events[6] == 'event: analysis_status\ndata: {"status": "preparing", "label": "正在整理内容…"}\n\n'
    assert events[7] == 'event: analysis_status\ndata: {"status": "answering", "label": "正在组织回复…"}\n\n'
    assert events[8] == (
        'event: error\ndata: {"code": "PROVIDER_ERROR", '
        '"message": "AI provider request failed."}\n\n'
    )
    assert all("event: done" not in event for event in events)


@pytest.mark.asyncio
async def test_chat_service_stream_meta_includes_persistence_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = "00000000-0000-4000-8000-000000000101"
    user_message_id = "00000000-0000-4000-8000-000000000102"
    assistant_message_id = "00000000-0000-4000-8000-000000000103"

    async def fake_prepare_persistence(*_, **__) -> PersistenceContext:
        return PersistenceContext(
            user_id="00000000-0000-4000-8000-000000000001",
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            assistant_message_id=assistant_message_id,
            user_content="hello",
        )

    async def fake_save_streamed_assistant(*_, **__) -> None:
        return None

    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("ALLOW_CLIENT_PROVIDER_CONFIG", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr("app.agent.ai_service.create_chat_client", lambda _: FakeClient())
    monkeypatch.setattr("app.agent.ai_service.prepare_persistence", fake_prepare_persistence)
    monkeypatch.setattr("app.agent.ai_service.save_streamed_assistant", fake_save_streamed_assistant)
    monkeypatch.setattr("app.agent.ai_service.schedule_after_response", lambda *_, **__: None)

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
    meta = json.loads(events[0].split("data: ", 1)[1])

    assert meta["conversation_id"] == conversation_id
    assert meta["user_message_id"] == user_message_id
    assert meta["assistant_message_id"] == assistant_message_id


@pytest.mark.asyncio
async def test_chat_service_marks_streaming_message_failed_on_client_abort(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assistant_message_id = "00000000-0000-4000-8000-000000000203"
    marked_failed: list[tuple[str | None, str]] = []

    async def fake_prepare_persistence(*_, **__) -> PersistenceContext:
        return PersistenceContext(
            user_id="00000000-0000-4000-8000-000000000001",
            conversation_id="00000000-0000-4000-8000-000000000201",
            user_message_id="00000000-0000-4000-8000-000000000202",
            assistant_message_id=assistant_message_id,
            user_content="hello",
        )

    async def fake_mark_assistant_failed(persistence: PersistenceContext, exc: Exception) -> None:
        marked_failed.append((persistence.assistant_message_id, str(exc)))

    monkeypatch.setenv("AI_API_KEY", "")
    monkeypatch.setenv("ALLOW_CLIENT_PROVIDER_CONFIG", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "")
    get_settings.cache_clear()
    monkeypatch.setattr("app.agent.ai_service.create_chat_client", lambda _: FakeClient())
    monkeypatch.setattr("app.agent.ai_service.prepare_persistence", fake_prepare_persistence)
    monkeypatch.setattr("app.agent.ai_service.mark_assistant_failed", fake_mark_assistant_failed)

    service = ChatService()
    request = ChatRequest(
        messages=[{"role": "user", "content": "hello"}],
        provider_config=ProviderConfig(
            base_url="https://client.example/v1",
            api_key="client-key",
            model="client-model",
        ),
    )

    stream = service.stream_chat(request)
    await anext(stream)
    await stream.aclose()
    await asyncio.sleep(0)

    assert marked_failed == [(assistant_message_id, "Stream interrupted")]

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.core.settings import get_settings
from app.middleware.request_size import RequestBodyLimitMiddleware


def test_json_body_size_limit(monkeypatch) -> None:
    monkeypatch.setenv("MAX_JSON_BODY_BYTES", "32")
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.post(
        "/api/chat",
        content='{"messages":[{"role":"user","content":"this body is too large"}]}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "REQUEST_TOO_LARGE"


def test_chat_rejects_too_many_messages() -> None:
    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": f"msg {index}"} for index in range(65)]},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def _run_body_limit(*, settings, path: str, headers, messages):
    sent = []
    completed = False

    async def app(_scope, receive, send):
        nonlocal completed
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            if not message.get("more_body", False):
                break
        completed = True
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    queue = list(messages)

    async def receive():
        if queue:
            return queue.pop(0)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    middleware = RequestBodyLimitMiddleware(app, settings=settings)
    await middleware(
        {"type": "http", "method": "POST", "path": path, "headers": headers},
        receive,
        send,
    )
    return sent, completed


@pytest.mark.asyncio
async def test_streamed_body_without_content_length_cannot_bypass_limit() -> None:
    settings = get_settings().model_copy(update={"max_json_body_bytes": 5})

    sent, completed = await _run_body_limit(
        settings=settings,
        path="/api/chat",
        headers=[(b"content-type", b"application/json")],
        messages=[
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ],
    )

    assert completed is False
    assert sent[0]["status"] == 413
    assert json.loads(sent[1]["body"])["error"]["code"] == "REQUEST_TOO_LARGE"


@pytest.mark.asyncio
async def test_multipart_route_uses_file_limit_plus_framing_allowance() -> None:
    settings = get_settings().model_copy(
        update={
            "max_json_body_bytes": 4,
            "document_max_file_bytes": 8,
            "max_multipart_overhead_bytes": 4,
        }
    )

    accepted, completed = await _run_body_limit(
        settings=settings,
        path="/api/documents/upload",
        headers=[(b"content-type", b"multipart/form-data; boundary=test")],
        messages=[{"type": "http.request", "body": b"x" * 12, "more_body": False}],
    )
    rejected, rejected_completed = await _run_body_limit(
        settings=settings,
        path="/api/documents/upload",
        headers=[(b"content-type", b"multipart/form-data; boundary=test")],
        messages=[{"type": "http.request", "body": b"x" * 13, "more_body": False}],
    )

    assert completed is True
    assert accepted[0]["status"] == 204
    assert rejected_completed is False
    assert rejected[0]["status"] == 413

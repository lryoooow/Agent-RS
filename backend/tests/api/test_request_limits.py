from fastapi.testclient import TestClient

from app.main import create_app
from app.core.settings import get_settings


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

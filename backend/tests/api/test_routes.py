from fastapi.testclient import TestClient

from app.api.deps import get_chat_service
from app.main import create_app
from app.core.settings import get_settings


def make_client() -> TestClient:
    get_settings.cache_clear()
    return TestClient(create_app())


def test_health_route(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path / "imagery"))
    client = make_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["storage_writable"] is True
    assert "api_key_configured" in body
    assert "docker_available" in body
    assert {
        name: value["image"]
        for name, value in body.items()
        if name.endswith("_mcp")
    } == {
        "rs_tools_mcp": "rs-tools-mcp:0.1.0",
        "rs_detect_mcp": "rs-detect-mcp:0.1.0",
        "rs_segment_mcp": "rs-segment-mcp:0.1.0",
        "rs_doc_mcp": "rs-doc-mcp:0.1.0",
    }
    for name in ("rs_tools_mcp", "rs_detect_mcp", "rs_segment_mcp", "rs_doc_mcp"):
        assert set(body[name]) == {"use_docker", "image", "docker_command_available"}


def test_config_route_does_not_leak_api_key(monkeypatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "sk-test-secret")
    client = make_client()

    response = client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["api_key_configured"] is True
    removed_field = "system_prompt" + "_template"
    assert removed_field not in body
    assert body["prompt_profile"] == "agent_rs_core_v1"
    assert body["prompt_dynamic_modules_enabled"] is True
    assert body["system_prompt_language"] == "zh-CN"
    assert body["allow_user_extra_instructions"] is True
    assert "sk-test-secret" not in response.text


def test_chat_route_validates_messages() -> None:
    client = make_client()

    response = client.post("/api/chat", json={"messages": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_chat_route_reports_missing_api_key(monkeypatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "")
    client = make_client()

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "CONFIG_ERROR"
    assert "API key" in body["error"]["message"]


def test_chat_route_streams_sse_response() -> None:
    class FakeChatService:
        async def stream_chat(self, _):
            yield 'event: meta\ndata: {"model": "fake", "provider": "test"}\n\n'
            yield 'event: delta\ndata: {"content": "hello"}\n\n'
            yield 'event: done\ndata: {"finish_reason": "stop"}\n\n'

    get_settings.cache_clear()
    app = create_app()
    app.dependency_overrides[get_chat_service] = lambda: FakeChatService()
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        json={"messages": [{"role": "user", "content": "hello"}], "stream": True},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: delta\ndata: {"content": "hello"}' in response.text

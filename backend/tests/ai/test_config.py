import pytest

from app.agent.config import resolve_ai_config
from app.agent.errors import ConfigError
from app.schemas.chat import ProviderConfig
from app.core.settings import get_settings


def reset_settings() -> None:
    get_settings.cache_clear()


def test_missing_api_key_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "")
    reset_settings()

    with pytest.raises(ConfigError, match="Missing AI API key"):
        resolve_ai_config()


def test_env_provider_config_wins_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", "env-model")
    monkeypatch.delenv("ALLOW_CLIENT_PROVIDER_CONFIG", raising=False)
    reset_settings()

    config = resolve_ai_config(
        request_model="request-model",
        provider_config=ProviderConfig(
            base_url="https://client.example/v1",
            api_key="client-key",
            model="client-model",
        ),
    )

    assert config.base_url == "https://env.example/v1"
    assert config.api_key == "env-key"
    assert config.model == "env-model"


def test_client_provider_config_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", "env-model")
    monkeypatch.setenv("ALLOW_CLIENT_PROVIDER_CONFIG", "true")
    reset_settings()

    config = resolve_ai_config(
        request_model="request-model",
        provider_config=ProviderConfig(
            base_url="https://client.example/v1",
            api_key="client-key",
            model="client-model",
        ),
    )

    assert config.base_url == "https://client.example/v1"
    assert config.api_key == "client-key"
    assert config.model == "client-model"
    assert config.trust_env_proxy is False


def test_request_model_can_override_env_only_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", "env-model")
    monkeypatch.setenv("ALLOW_CLIENT_PROVIDER_CONFIG", "true")
    reset_settings()

    config = resolve_ai_config(request_model="request-model")

    assert config.model == "request-model"


def test_client_provider_config_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", "env-model")
    monkeypatch.setenv("ALLOW_CLIENT_PROVIDER_CONFIG", "false")
    reset_settings()

    config = resolve_ai_config(
        provider_config=ProviderConfig(
            base_url="https://client.example/v1",
            api_key="client-key",
            model="client-model",
        ),
    )

    assert config.base_url == "https://env.example/v1"
    assert config.api_key == "env-key"
    assert config.model == "env-model"

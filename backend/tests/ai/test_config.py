import pytest

from app.agent.config import resolve_ai_config
from app.agent.errors import ConfigError
from app.schemas.chat import ProviderConfig
from app.core.settings import get_settings


def reset_settings() -> None:
    get_settings.cache_clear()


def _set_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """统一铺设 env 三件套，作为降级链的兜底来源。"""
    monkeypatch.setenv("AI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", "env-model")
    reset_settings()


# ---------- 异常：缺失即报错（env 与 client 都空）----------

def test_missing_api_key_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_API_KEY", "")
    reset_settings()
    with pytest.raises(ConfigError, match="Missing AI API key"):
        resolve_ai_config()


def test_missing_base_url_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # base_url 有代码默认值（openai 官方），需显式置空才命中缺失分支。
    monkeypatch.setenv("AI_BASE_URL", "")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    reset_settings()
    with pytest.raises(ConfigError, match="Missing AI base URL"):
        resolve_ai_config()


def test_missing_model_raises_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_BASE_URL", "https://env.example/v1")
    monkeypatch.setenv("AI_API_KEY", "env-key")
    monkeypatch.setenv("AI_DEFAULT_MODEL", "")
    reset_settings()
    with pytest.raises(ConfigError, match="Missing AI model"):
        resolve_ai_config()


# ---------- 常规：前端填了就用（覆盖 env）----------

def test_client_provider_config_always_applied_when_provided(monkeypatch: pytest.MonkeyPatch) -> None:
    # 新契约（用户明确要求）：前端配置页填的 provider_config 始终生效，不再由任何
    # 服务端开关门控。历史上的 allow_client_provider_config "false 时丢弃 client" 行为
    # 已从 resolve_ai_config 移除，故这里断言 client 三项均覆盖 env（填了就用）。
    _set_env(monkeypatch)
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


# ---------- 常规：前端留空则回落 env（降级方向）----------

def test_client_config_falls_back_to_env_when_client_blank(monkeypatch: pytest.MonkeyPatch) -> None:
    # 前端三项留空（None）时，or 链兜底到 env，保证"只在 env 填 key、前端不填"用法不破。
    _set_env(monkeypatch)
    config = resolve_ai_config(
        provider_config=ProviderConfig(base_url=None, api_key=None, model=None),
    )
    assert config.base_url == "https://env.example/v1"
    assert config.api_key == "env-key"
    assert config.model == "env-model"
    assert config.trust_env_proxy is False


# ---------- 边界：前端只填部分字段，其余各自回落 env ----------

def test_client_partial_config_mixes_with_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # 只填 api_key（典型场景：换个 key 但用同一 base_url/model）。
    _set_env(monkeypatch)
    config = resolve_ai_config(
        provider_config=ProviderConfig(base_url=None, api_key="client-key", model=None),
    )
    assert config.base_url == "https://env.example/v1"  # 回落 env
    assert config.api_key == "client-key"               # 用前端
    assert config.model == "env-model"                  # 回落 env


# ---------- 边界：request_model 覆盖 env 默认模型 ----------

def test_request_model_overrides_env_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    config = resolve_ai_config(request_model="request-model")
    assert config.model == "request-model"


# ---------- 边界：provider_config.model 优先级高于 request_model ----------

def test_client_model_takes_precedence_over_request_model(monkeypatch: pytest.MonkeyPatch) -> None:
    # 解析顺序 client_model or request_model or env：前端配置页填的模型最高优先。
    _set_env(monkeypatch)
    config = resolve_ai_config(
        request_model="request-model",
        provider_config=ProviderConfig(base_url=None, api_key=None, model="client-model"),
    )
    assert config.model == "client-model"

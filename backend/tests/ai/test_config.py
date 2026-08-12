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


# ---------- 常规：允许且合规时，前端值覆盖 env ----------

def test_client_provider_config_applied_when_allowed_and_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    # 契约：allow_client_provider_config=True（默认）且客户端 base_url 通过 SSRF 校验、
    # 覆盖 base_url 时自带 api_key → 客户端三项覆盖 env。白名单内主机跳过 DNS（测试免联网）。
    _set_env(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_ALLOWED_HOSTS", "client.example")
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


# ---------- 安全：门控 / SSRF / 密钥外泄（P0-1 回归） ----------

def test_allow_client_provider_config_false_ignores_client(monkeypatch: pytest.MonkeyPatch) -> None:
    # 公网部署设 false：客户端 provider_config 被整块忽略，回落 env。
    _set_env(monkeypatch)
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


def test_client_base_url_override_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # 覆盖 base_url 但不带 api_key → 拒绝（绝不把服务端 key 发往客户端 URL）。
    _set_env(monkeypatch)
    monkeypatch.setenv("AI_PROVIDER_ALLOWED_HOSTS", "client.example")
    reset_settings()
    with pytest.raises(ConfigError, match="必须同时提供 api_key"):
        resolve_ai_config(
            provider_config=ProviderConfig(base_url="https://client.example/v1", api_key=None),
        )


def test_client_base_url_rejects_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_env(monkeypatch)
    reset_settings()
    with pytest.raises(ConfigError, match="内网/保留地址"):
        resolve_ai_config(
            provider_config=ProviderConfig(base_url="https://10.0.0.1/v1", api_key="k"),
        )


def test_client_base_url_rejects_http_metadata_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    # 云元数据端点 http 且非回环 → 拒（SSRF 防护）。
    _set_env(monkeypatch)
    reset_settings()
    with pytest.raises(ConfigError, match="仅回环允许 http"):
        resolve_ai_config(
            provider_config=ProviderConfig(
                base_url="http://169.254.169.254/latest/meta-data/", api_key="k",
            ),
        )


def test_client_base_url_allows_loopback_http(monkeypatch: pytest.MonkeyPatch) -> None:
    # 本地开发：回环 http 放行（Ollama 等）。
    _set_env(monkeypatch)
    reset_settings()
    config = resolve_ai_config(
        provider_config=ProviderConfig(base_url="http://127.0.0.1:11434/v1", api_key="local-key"),
    )
    assert config.base_url == "http://127.0.0.1:11434/v1"
    assert config.api_key == "local-key"


def test_provider_config_schema_rejects_non_http_scheme() -> None:
    # API 边界即拒 file:///ftp:// 等（pydantic 层）。
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ProviderConfig(base_url="file:///etc/passwd")


# ---------- 思考强度分档：strength → budget ----------

def test_resolve_thinking_budget_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent.config import resolve_thinking_budget

    monkeypatch.setenv("AI_THINKING_BUDGET", "128")
    monkeypatch.setenv("AI_THINKING_BUDGET_LOW", "100")
    monkeypatch.setenv("AI_THINKING_BUDGET_MEDIUM", "1000")
    monkeypatch.setenv("AI_THINKING_BUDGET_MAX", "9000")
    reset_settings()
    assert resolve_thinking_budget("low") == 100
    assert resolve_thinking_budget("medium") == 1000
    assert resolve_thinking_budget("max") == 9000
    assert resolve_thinking_budget(None) == 128  # 旧客户端 / None 回落服务端默认
    assert resolve_thinking_budget("bogus") == 128  # 未知值安全回落


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

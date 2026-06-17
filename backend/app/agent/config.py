from dataclasses import dataclass

from app.agent.errors import ConfigError
from app.schemas.chat import ProviderConfig
from app.core.settings import get_settings


@dataclass(frozen=True)
class ResolvedAIConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    max_retries: int
    trust_env_proxy: bool


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def resolve_ai_config(
    request_model: str | None = None,
    provider_config: ProviderConfig | None = None,
) -> ResolvedAIConfig:
    settings = get_settings()
    # 前端配置页填的 provider_config 始终参与降级：填了就用、留空则回落 env。
    # 是否「采用前端值」不再由服务端开关门控——这正是 client_xxx or settings.xxx 链的语义。
    client_base_url = _clean(provider_config.base_url if provider_config else None)
    client_api_key = _clean(provider_config.api_key if provider_config else None)
    client_model = _clean(provider_config.model if provider_config else None)
    request_model = _clean(request_model)

    base_url = client_base_url or _clean(settings.ai_base_url)
    api_key = client_api_key or _clean(settings.ai_api_key)
    model = client_model or request_model or _clean(settings.ai_default_model)

    if not base_url:
        raise ConfigError("Missing AI base URL.")
    if not api_key:
        raise ConfigError("Missing AI API key.")
    if not model:
        raise ConfigError("Missing AI model.")

    return ResolvedAIConfig(
        provider=settings.ai_provider,
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_seconds=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
        trust_env_proxy=settings.ai_trust_env_proxy,
    )

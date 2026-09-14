import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.agent.errors import ConfigError
from app.schemas.chat import ProviderConfig
from app.core.settings import Settings, get_settings


@dataclass(frozen=True)
class ResolvedAIConfig:
    provider: str
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float
    max_retries: int
    trust_env_proxy: bool
    thinking_strength: str | None = None


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _is_blocked_ip(addr) -> bool:
    """内网/链路本地/保留/组播/未指定地址一律拒绝作为客户端 base_url 目标（SSRF 防护）。

    回环不在此列——本地开发（Ollama 等 http://localhost）需要它。
    """
    return (
        addr.is_private
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _validate_client_base_url(url: str, settings: Settings) -> str:
    """校验客户端提供的 base_url，阻断 SSRF 与密钥外泄信道。

    规则：
    - scheme 仅允许 https；回环（localhost/127.0.0.1/::1）放宽允许 http（本地开发）。
      云元数据端点（http://169.254.169.254）等明文内网目标由此被挡。
    - IP 字面量：非回环且落在私网/链路本地/保留/组播段 → 拒绝。
    - 主机名：命中 settings.ai_provider_allowed_host_set 的跳过解析（可信内网/测试）；
      其余解析 DNS，任一解析地址落在阻断段 → 拒绝；无法解析 → 拒绝（不可达且防绕过）。
    """
    parsed = urlsplit(url)
    scheme = (parsed.scheme or "").lower()
    hostname = parsed.hostname
    if scheme not in ("http", "https"):
        raise ConfigError("provider base_url 必须是 http(s) 地址。")
    if not hostname:
        raise ConfigError("provider base_url 缺少主机名。")

    is_loopback_name = hostname.lower() == "localhost"
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        ip = None
    is_loopback = is_loopback_name or (ip is not None and ip.is_loopback)

    if scheme == "http" and not is_loopback:
        raise ConfigError("provider base_url 仅回环允许 http，外部地址必须 https。")

    if ip is not None:
        if not ip.is_loopback and _is_blocked_ip(ip):
            raise ConfigError("provider base_url 指向内网/保留地址，已拒绝。")
        return url

    # 主机名
    if hostname.lower() in settings.ai_provider_allowed_host_set:
        return url
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise ConfigError(f"provider base_url 主机无法解析：{hostname}") from exc
    for entry in infos:
        sockaddr = entry[4]
        try:
            resolved = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            continue
        if not resolved.is_loopback and _is_blocked_ip(resolved):
            # 常见误伤：本机跑着 fake-ip 代理（Clash TUN 等）时，所有域名都解析到
            # 198.18.0.0/15 保留段。流量经代理是通的，只是校验过不去——把主机加进
            # AI_PROVIDER_ALLOWED_HOSTS 即可跳过 DNS 校验（白名单命中在解析之前）。
            raise ConfigError(
                f"provider base_url 解析到内网/保留地址（{hostname} -> {resolved}），已拒绝。"
                "若本机使用 fake-ip 代理（Clash TUN 等），请在服务端 .env 的 "
                "AI_PROVIDER_ALLOWED_HOSTS 里加上该主机后重启。"
            )
    return url


THINKING_STRENGTHS: tuple[str, ...] = ("low", "medium", "max")


def resolve_thinking_budget(strength: str | None) -> int:
    """思考强度 → token 预算。三档都开思考、预算真正拉开（时长/速度/精度不同）。

    None / 未知值回落 settings.ai_thinking_budget（旧客户端兼容，行为不变）。
    """
    settings = get_settings()
    if strength == "low":
        return settings.ai_thinking_budget_low
    if strength == "medium":
        return settings.ai_thinking_budget_medium
    if strength == "max":
        return settings.ai_thinking_budget_max
    return settings.ai_thinking_budget


def resolve_ai_config(
    request_model: str | None = None,
    provider_config: ProviderConfig | None = None,
    thinking_strength: str | None = None,
) -> ResolvedAIConfig:
    settings = get_settings()
    # 安全门控：allow_client_provider_config=False 时整块忽略客户端 provider_config，
    # 锁定服务端 env 配置（公网多用户部署应设 false）。
    if provider_config is not None and not settings.allow_client_provider_config:
        provider_config = None
    client_base_url = _clean(provider_config.base_url if provider_config else None)
    client_api_key = _clean(provider_config.api_key if provider_config else None)
    client_model = _clean(provider_config.model if provider_config else None)
    request_model = _clean(request_model)

    # 防 SSRF / 密钥外泄：客户端覆盖 base_url 时必须自带 api_key（绝不把服务端
    # AI_API_KEY 发往客户端指定 URL），并对 base_url 做 SSRF 校验。
    if client_base_url:
        if not client_api_key:
            raise ConfigError("覆盖 base_url 时必须同时提供 api_key。")
        client_base_url = _validate_client_base_url(client_base_url, settings)

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
        thinking_strength=thinking_strength,
    )

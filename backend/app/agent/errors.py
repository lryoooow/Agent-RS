import logging

from app.core.error_logging import log_exception_diagnostics


logger = logging.getLogger(__name__)


class AIError(Exception):
    code = "PROVIDER_ERROR"
    status_code = 502

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message)


class ConversationAccessError(AIError):
    code = "CONVERSATION_NOT_FOUND"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("会话不存在或无权访问。")


class PersistenceUnavailableError(AIError):
    code = "PERSISTENCE_UNAVAILABLE"
    status_code = 503

    def __init__(self) -> None:
        super().__init__("聊天持久化暂时不可用，请稍后重试。")


class ContextBudgetError(AIError):
    code = "CONTEXT_BUDGET_EXCEEDED"
    status_code = 413

    def __init__(self):
        super().__init__("当前请求和必要系统规则超过上下文预算，请缩短问题或调整服务端预算。")


class ConfigError(AIError):
    code = "CONFIG_ERROR"
    status_code = 400


class EmptyResponseError(AIError):
    code = "EMPTY_AI_RESPONSE"

    def __init__(self):
        super().__init__("模型未返回可展示的答复，请查看本轮任务状态。")


class AuthError(AIError):
    code = "AUTH_ERROR"
    status_code = 401


class RateLimitError(AIError):
    code = "RATE_LIMIT_ERROR"
    status_code = 429


class NetworkError(AIError):
    code = "NETWORK_ERROR"
    status_code = 503


class ProviderError(AIError):
    code = "PROVIDER_ERROR"
    status_code = 502


def map_provider_error(exc: Exception) -> AIError:
    name = exc.__class__.__name__.lower()
    status_code = getattr(exc, "status_code", None)

    if status_code == 401 or "auth" in name:
        mapped = AuthError("AI 模型供应商认证失败，请在右上角“配置”中更新当前用户的 API Key 后重试。")
    elif status_code == 429 or "ratelimit" in name or "rate_limit" in name:
        mapped = RateLimitError("AI 模型供应商请求频率已达上限，请稍后重试。")
    elif "timeout" in name or "connection" in name or "network" in name:
        mapped = NetworkError("AI 模型供应商网络请求失败，请检查 Provider Base URL 和网络设置。")
    else:
        mapped = ProviderError("AI 模型供应商请求失败，请稍后重试。")

    log_exception_diagnostics(
        logger,
        "ai.provider_error",
        exc,
        mapped_code=mapped.code,
        mapped_status=mapped.status_code,
    )
    return mapped

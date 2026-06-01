class AIError(Exception):
    code = "PROVIDER_ERROR"
    status_code = 502

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message)


class ConfigError(AIError):
    code = "CONFIG_ERROR"
    status_code = 400


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
        return AuthError("AI provider authentication failed.")
    if status_code == 429 or "ratelimit" in name or "rate_limit" in name:
        return RateLimitError("AI provider rate limit exceeded.")
    if "timeout" in name or "connection" in name or "network" in name:
        return NetworkError("AI provider network request failed. Check provider base URL and proxy settings.")

    return ProviderError("AI provider request failed.")

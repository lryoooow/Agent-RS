from __future__ import annotations

from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from app.shared.settings import Settings


def create_embedding_client(settings: Settings) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.resolved_embedding_base_url or None,
        api_key=settings.resolved_embedding_api_key,
        timeout=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
        http_client=DefaultAsyncHttpxClient(trust_env=settings.ai_trust_env_proxy),
    )

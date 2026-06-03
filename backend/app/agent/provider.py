from openai import AsyncOpenAI, DefaultAsyncHttpxClient

from app.agent.config import ResolvedAIConfig


def create_chat_client(config: ResolvedAIConfig) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        timeout=config.timeout_seconds,
        max_retries=config.max_retries,
        http_client=DefaultAsyncHttpxClient(trust_env=config.trust_env_proxy),
    )

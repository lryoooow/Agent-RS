"""OpenAI-compatible LangChain model using the same resolved per-request provider."""
from types import SimpleNamespace

import httpx
from langchain_openai import ChatOpenAI

from app.agent.engine.model_client import thinking_extra_body


class LangGraphModelClient:
    def __init__(self, config):
        self.http = httpx.Client(trust_env=config.trust_env_proxy)
        self.async_http = httpx.AsyncClient(trust_env=config.trust_env_proxy)
        self.model = ChatOpenAI(model=config.model, api_key=config.api_key, base_url=config.base_url,
            timeout=config.timeout_seconds, max_retries=config.max_retries, streaming=True, stream_usage=True,
            use_responses_api=False, http_client=self.http, http_async_client=self.async_http,
            extra_body=thinking_extra_body(enable=True, strength=config.thinking_strength))
        self.input_tokens = self.output_tokens = 0

    def collect_usage(self, usage):
        self.input_tokens += (usage or {}).get("input_tokens", 0)
        self.output_tokens += (usage or {}).get("output_tokens", 0)

    def total_usage(self):
        return SimpleNamespace(prompt_tokens=self.input_tokens, completion_tokens=self.output_tokens)

    async def close(self):
        try:
            await self.async_http.aclose()
        finally:
            self.http.close()

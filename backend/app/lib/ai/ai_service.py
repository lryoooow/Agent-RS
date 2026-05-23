from typing import AsyncIterator

from app.lib.ai.config import resolve_ai_config
from app.lib.ai.errors import AIError, map_provider_error
from app.lib.ai.normalizer import normalize_chat_response
from app.lib.ai.provider import create_chat_client
from app.lib.ai.request_builder import build_provider_messages
from app.lib.ai.stream import sse_event, stream_sse_events
from app.schemas.chat import ChatRequest, ChatResponse


class AIService:
    async def chat(self, request: ChatRequest) -> ChatResponse:
        config = resolve_ai_config(
            request_model=request.model,
            provider_config=request.provider_config,
        )
        messages = build_provider_messages(request)
        client = create_chat_client(config)

        try:
            response = await client.chat.completions.create(
                model=config.model,
                messages=messages,
                stream=False,
            )
        except Exception as exc:
            raise map_provider_error(exc) from exc

        return normalize_chat_response(response, config)

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        try:
            config = resolve_ai_config(
                request_model=request.model,
                provider_config=request.provider_config,
            )
            messages = build_provider_messages(request)
            client = create_chat_client(config)
            stream = await client.chat.completions.create(
                model=config.model,
                messages=messages,
                stream=True,
            )
        except Exception as exc:
            error = exc if isinstance(exc, AIError) else map_provider_error(exc)
            yield sse_event("error", {"code": error.code, "message": error.message})
            return

        async for event in stream_sse_events(stream, config):
            yield event

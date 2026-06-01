from typing import AsyncIterator

from app.lib.ai.ai_service import AIService
from app.schemas.chat import ChatRequest, ChatResponse


class ChatService:
    def __init__(self, ai_service: AIService | None = None) -> None:
        self.ai_service = ai_service or AIService()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        return await self.ai_service.chat(request)

    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[str]:
        stream = self.ai_service.stream_chat(request)
        try:
            async for event in stream:
                yield event
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose:
                await aclose()

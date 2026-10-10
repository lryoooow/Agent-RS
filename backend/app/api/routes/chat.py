from uuid import UUID

import asyncio
from collections.abc import AsyncIterator
from contextvars import copy_context

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.agent.errors import ConversationAccessError, PersistenceUnavailableError
from app.api.deps import get_chat_service, require_authenticated_user
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool
from app.db.repositories.conversation import get_conversation
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.chat_service import ChatService

router = APIRouter(tags=["chat"])


_SSE_HEARTBEAT_SECONDS = 15.0


async def stream_with_heartbeat(
    source: AsyncIterator[str],
    *,
    interval_seconds: float = _SSE_HEARTBEAT_SECONDS,
) -> AsyncIterator[str]:
    """Forward an SSE stream and emit comments while a tool is silent.

    Long raster imports can spend minutes inside one tool call.  Without bytes on
    the wire, the browser's idle watchdog treats a healthy request as failed and
    disconnects while the durable tool job continues in the background.
    """
    # Reuse one request-local Context: a fresh task's default copy would discard
    # scopes established inside the generator at the preceding yield.
    context = copy_context()
    pending = asyncio.create_task(anext(source), context=context)
    try:
        while True:
            done, _ = await asyncio.wait({pending}, timeout=interval_seconds)
            if not done:
                yield ": keepalive\n\n"
                continue
            try:
                item = pending.result()
            except StopAsyncIteration:
                return
            yield item
            pending = asyncio.create_task(anext(source), context=context)
    finally:
        if not pending.done():
            pending.cancel()
        try:
            await asyncio.gather(pending, return_exceptions=True)
        finally:
            # Closing may unwind ContextVar tokens too. Wait for the reader to
            # stop before closing, and unwind in the same isolated Context.
            await asyncio.create_task(source.aclose(), context=context)


async def _authorize_requested_conversation(
    conversation_id: str | None,
    *,
    user_id: str,
) -> None:
    """Validate conversation ownership before a JSON/SSE response is started.

    The persistence layer repeats this check as a data-boundary backstop. Doing it
    here as well is necessary for streaming: once StreamingResponse sends headers,
    a permission error can only become an SSE event with an incorrect HTTP 200.
    """
    if not conversation_id or not get_settings().storage_active:
        return
    try:
        normalized_id = str(UUID(conversation_id))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ConversationAccessError() from exc

    pool = await fetch_optional_pool()
    if pool is None:
        raise PersistenceUnavailableError()
    async with pool.acquire() as conn:
        if not await get_conversation(conn, normalized_id, user_id):
            # Same response for missing and foreign conversations prevents an
            # authenticated caller from probing another user's identifiers.
            raise ConversationAccessError()


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat(
    request: ChatRequest,
    chat_service: ChatService = Depends(get_chat_service),
    user_id: str = Depends(require_authenticated_user),
) -> ChatResponse | StreamingResponse:
    await _authorize_requested_conversation(
        request.conversation_id,
        user_id=user_id,
    )
    if request.stream:
        return StreamingResponse(
            stream_with_heartbeat(chat_service.stream_chat(request)),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return await chat_service.chat(request)

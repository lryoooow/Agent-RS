from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TypeAlias

from app.lib.ai.embedding.service import get_embedding_service
from app.lib.ai.memory_judge import maybe_store_memory
from app.lib.auth import get_current_user_id
from app.lib.db.pool import fetch_optional_pool
from app.lib.db.repositories.conversation import create_conversation, get_conversation, touch_conversation
from app.lib.db.repositories.identity import ensure_default_identity
from app.lib.db.repositories.message import (
    add_embedding_retry,
    append_message,
    set_embedding,
    update_message_complete,
)
from app.schemas.chat import ChatRequest
from app.shared.settings import get_settings

logger = logging.getLogger(__name__)

EmbeddingTarget: TypeAlias = tuple[str, str]


@dataclass
class PersistenceContext:
    user_id: str
    conversation_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    user_content: str = ""


async def prepare_persistence(
    request: ChatRequest,
    *,
    model_name: str,
    create_streaming_assistant: bool = False,
) -> PersistenceContext:
    user_id = get_current_user_id()
    context = PersistenceContext(user_id=user_id, user_content=latest_user_content(request))
    settings = get_settings()
    if not settings.database_enabled:
        context.conversation_id = request.conversation_id
        return context

    pool = await fetch_optional_pool()
    if pool is None:
        context.conversation_id = request.conversation_id
        return context

    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await ensure_default_identity(conn, settings)
                conversation_id = request.conversation_id
                if conversation_id and not await get_conversation(conn, conversation_id, user_id):
                    conversation_id = None
                if not conversation_id:
                    conversation_id = await create_conversation(
                        conn,
                        user_id=user_id,
                        settings=settings,
                        model_name=model_name,
                    )
                context.conversation_id = conversation_id
                context.user_message_id = await append_message(
                    conn,
                    conversation_id=conversation_id,
                    role="user",
                    content=context.user_content,
                    status="complete",
                )
                if create_streaming_assistant:
                    context.assistant_message_id = await append_message(
                        conn,
                        conversation_id=conversation_id,
                        role="assistant",
                        content="",
                        status="streaming",
                    )
                await touch_conversation(conn, conversation_id)
    except Exception:
        logger.exception("Database persistence setup failed; falling back to stateless chat.")
        context.conversation_id = request.conversation_id
        context.user_message_id = None
        context.assistant_message_id = None
    return context


async def save_assistant_response(
    persistence: PersistenceContext,
    *,
    content: str,
    usage: dict,
    finish_reason: str | None,
) -> str | None:
    if not persistence.conversation_id:
        return None
    pool = await fetch_optional_pool()
    if pool is None:
        return None
    try:
        async with pool.acquire() as conn:
            message_id = await append_message(
                conn,
                conversation_id=persistence.conversation_id,
                role="assistant",
                content=content,
                status="complete",
                metadata={"finish_reason": finish_reason},
                tokens_in=_optional_int(usage.get("input_tokens")),
                tokens_out=_optional_int(usage.get("output_tokens")),
            )
            await touch_conversation(conn, persistence.conversation_id)
            return message_id
    except Exception:
        logger.exception("Failed to save assistant response.")
        return None


async def save_streamed_assistant(
    persistence: PersistenceContext,
    *,
    content: str,
    done_payload: dict,
) -> None:
    if not persistence.assistant_message_id:
        return
    pool = await fetch_optional_pool()
    if pool is None:
        return
    usage = done_payload.get("usage") or {}
    try:
        async with pool.acquire() as conn:
            await update_message_complete(
                conn,
                message_id=persistence.assistant_message_id,
                content=content,
                status="complete",
                metadata={"finish_reason": done_payload.get("finish_reason")},
                tokens_in=_optional_int(usage.get("input_tokens")),
                tokens_out=_optional_int(usage.get("output_tokens")),
            )
            if persistence.conversation_id:
                await touch_conversation(conn, persistence.conversation_id)
    except Exception:
        logger.exception("Failed to save streamed assistant response.")


async def mark_assistant_failed(persistence: PersistenceContext, exc: Exception) -> None:
    if not persistence.assistant_message_id:
        return
    pool = await fetch_optional_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            await update_message_complete(
                conn,
                message_id=persistence.assistant_message_id,
                content="",
                status="failed",
                metadata={"error": str(exc)},
            )
    except Exception:
        logger.exception("Failed to mark assistant message as failed.")


def schedule_after_response(
    persistence: PersistenceContext,
    *,
    assistant_content: str,
) -> None:
    if not persistence.conversation_id:
        return
    embedding_targets: list[EmbeddingTarget] = [
        (message_id, content)
        for message_id, content in (
            (persistence.user_message_id, persistence.user_content),
            (persistence.assistant_message_id, assistant_content),
        )
        if message_id and content.strip()
    ]
    if embedding_targets:
        asyncio.create_task(_embed_messages(embedding_targets))
    if persistence.assistant_message_id:
        asyncio.create_task(
            maybe_store_memory(
                user_id=persistence.user_id,
                conversation_id=persistence.conversation_id,
                user_content=persistence.user_content,
                assistant_content=assistant_content,
                source_message_id=persistence.assistant_message_id,
            )
        )


def persistence_meta(persistence: PersistenceContext) -> dict[str, str]:
    return {
        key: value
        for key, value in {
            "conversation_id": persistence.conversation_id,
            "user_message_id": persistence.user_message_id,
            "assistant_message_id": persistence.assistant_message_id,
        }.items()
        if value
    }


def request_for_context(request: ChatRequest, persistence: PersistenceContext) -> ChatRequest:
    if not request.conversation_id:
        return request
    if request.conversation_id == persistence.conversation_id:
        return request
    return request.model_copy(update={"conversation_id": persistence.conversation_id})


def latest_user_content(request: ChatRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return request.messages[-1].content


def _optional_int(value: object) -> int | None:
    return int(value) if value is not None else None


async def _embed_messages(targets: list[EmbeddingTarget]) -> None:
    pool = await fetch_optional_pool()
    if pool is None:
        return
    message_ids = [message_id for message_id, _ in targets]
    contents = [content for _, content in targets]
    try:
        vectors = await get_embedding_service().embed_batch(contents)
    except Exception as exc:
        try:
            async with pool.acquire() as conn:
                for message_id in message_ids:
                    await add_embedding_retry(conn, message_id=message_id, error=str(exc))
        except Exception:
            logger.exception("Failed to enqueue embedding retry.")
        return
    try:
        async with pool.acquire() as conn:
            for message_id, vector in zip(message_ids, vectors, strict=False):
                await set_embedding(conn, message_id=message_id, embedding=vector)
    except Exception:
        logger.exception("Failed to save message embeddings.")

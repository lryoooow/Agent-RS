from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.lib.auth import get_current_user_id
from app.lib.db.pool import fetch_optional_pool
from app.lib.db.repositories.conversation import (
    delete_conversation,
    get_conversation,
    list_conversations,
    update_conversation_title,
)
from app.lib.db.repositories.message import list_conversation_messages

router = APIRouter(tags=["conversations"])


class ConversationItem(BaseModel):
    id: str
    title: str
    scenario_id: str | None = None
    model_name: str | None = None
    message_count: int
    created_at: str
    updated_at: str


class ConversationListResponse(BaseModel):
    conversations: list[ConversationItem]


class ConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class ConversationMessageItem(BaseModel):
    id: str
    role: str
    content: str
    status: str
    metadata: dict[str, Any] | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    created_at: str


class ConversationMessagesResponse(BaseModel):
    messages: list[ConversationMessageItem]


@router.get("/conversations", response_model=ConversationListResponse)
async def list_user_conversations(
    limit: int = Query(default=50, ge=1, le=100),
) -> ConversationListResponse:
    pool = await _require_db()
    user_id = get_current_user_id()
    async with pool.acquire() as conn:
        rows = await list_conversations(conn, user_id=user_id, limit=limit)
    return ConversationListResponse(
        conversations=[
            ConversationItem(
                id=row["id"],
                title=row["title"],
                scenario_id=row["scenario_id"],
                model_name=row["model_name"],
                message_count=row["message_count"],
                created_at=_iso(row["created_at"]),
                updated_at=_iso(row["updated_at"]),
            )
            for row in rows
        ]
    )


@router.get("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
async def list_user_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=100, ge=1, le=100),
    before: str | None = None,
) -> ConversationMessagesResponse:
    pool = await _require_db()
    user_id = get_current_user_id()
    async with pool.acquire() as conn:
        if not await get_conversation(conn, conversation_id, user_id):
            raise HTTPException(
                status_code=404,
                detail={"code": "CONVERSATION_NOT_FOUND", "message": "Conversation was not found."},
            )
        rows = await list_conversation_messages(
            conn,
            conversation_id=conversation_id,
            limit=limit,
            before=before,
        )
    return ConversationMessagesResponse(
        messages=[
            ConversationMessageItem(
                id=row["id"],
                role=row["role"],
                content=row["content"],
                status=row["status"],
                metadata=row["metadata_json"],
                tokens_in=row["tokens_in"],
                tokens_out=row["tokens_out"],
                created_at=_iso(row["created_at"]),
            )
            for row in rows
        ]
    )


@router.patch("/conversations/{conversation_id}")
async def update_user_conversation(
    conversation_id: str,
    request: ConversationUpdateRequest,
) -> dict[str, bool]:
    pool = await _require_db()
    async with pool.acquire() as conn:
        updated = await update_conversation_title(
            conn,
            conversation_id=conversation_id,
            user_id=get_current_user_id(),
            title=request.title.strip(),
        )
    if not updated:
        raise HTTPException(
            status_code=404,
            detail={"code": "CONVERSATION_NOT_FOUND", "message": "Conversation was not found."},
        )
    return {"updated": True}


@router.delete("/conversations/{conversation_id}")
async def delete_user_conversation(conversation_id: str) -> dict[str, bool]:
    pool = await _require_db()
    async with pool.acquire() as conn:
        async with conn.transaction():
            deleted = await delete_conversation(
                conn,
                conversation_id=conversation_id,
                user_id=get_current_user_id(),
            )
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "CONVERSATION_NOT_FOUND", "message": "Conversation was not found."},
        )
    return {"deleted": True}


async def _require_db():
    pool = await fetch_optional_pool()
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "DATABASE_UNAVAILABLE", "message": "Database is unavailable."},
        )
    return pool


def _iso(value: Any) -> str:
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)

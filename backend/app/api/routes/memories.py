from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.lib.auth import get_current_user_id
from app.lib.db.pool import fetch_optional_pool
from app.lib.db.repositories.memory import delete_memory, list_memories

router = APIRouter(tags=["memories"])


class MemoryItem(BaseModel):
    id: str
    content: str
    memory_type: str
    importance: float
    metadata: dict[str, Any] | None = None
    created_at: str


class MemoryListResponse(BaseModel):
    memories: list[MemoryItem]


@router.get("/memories", response_model=MemoryListResponse)
async def list_user_memories(limit: int = Query(default=100, ge=1, le=200)) -> MemoryListResponse:
    pool = await _require_db()
    async with pool.acquire() as conn:
        rows = await list_memories(conn, user_id=get_current_user_id(), limit=limit)
    return MemoryListResponse(
        memories=[
            MemoryItem(
                id=row["id"],
                content=row["content"],
                memory_type=row["memory_type"],
                importance=float(row["importance"]),
                metadata=row["metadata"],
                created_at=_iso(row["created_at"]),
            )
            for row in rows
        ]
    )


@router.delete("/memories/{memory_id}")
async def delete_user_memory(memory_id: str) -> dict[str, bool]:
    pool = await _require_db()
    async with pool.acquire() as conn:
        deleted = await delete_memory(conn, user_id=get_current_user_id(), memory_id=memory_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={"code": "MEMORY_NOT_FOUND", "message": "Memory was not found."},
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

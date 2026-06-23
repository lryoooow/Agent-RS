from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import require_admin
from app.auth import get_current_user_id
from app.auth.invites import generate_invite_code, hash_invite_code
from app.db.pool import fetch_optional_pool
from app.db.repositories.auth import list_users, set_user_active
from app.db.repositories.invite import (
    create_invite,
    list_invites,
    revoke_invite,
)
from app.core.settings import get_settings

# 全部管理端点统一挂 require_admin：非管理员 403，未登录 401（由依赖内部区分）。
router = APIRouter(tags=["admin"], dependencies=[Depends(require_admin)])


class CreateInviteRequest(BaseModel):
    label: str = Field(default="", max_length=200)
    expires_in_days: int | None = Field(default=None, ge=1, le=365)
    max_uses: int = Field(default=1, ge=1, le=100)


class InviteItem(BaseModel):
    id: str
    label: str
    expires_at: str | None = None
    max_uses: int
    used_count: int
    revoked: bool
    created_at: str


class CreateInviteResponse(BaseModel):
    invite: InviteItem
    # 明文邀请码仅在创建时返回这一次；DB 只存 HMAC，之后无法再取回。
    code: str


class InviteListResponse(BaseModel):
    invites: list[InviteItem]


class AdminUserItem(BaseModel):
    id: str
    email: str
    name: str
    is_active: bool
    is_admin: bool
    created_at: str


class AdminUserListResponse(BaseModel):
    users: list[AdminUserItem]


@router.post("/admin/invites", response_model=CreateInviteResponse)
async def admin_create_invite(request: CreateInviteRequest) -> CreateInviteResponse:
    settings = get_settings()
    pool = await _require_db()
    code = generate_invite_code()
    code_hash = hash_invite_code(code, settings.auth_secret_key)
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=request.expires_in_days)
        if request.expires_in_days
        else None
    )
    async with pool.acquire() as conn:
        row = await create_invite(
            conn,
            code_hash=code_hash,
            created_by_user_id=get_current_user_id(),
            label=request.label.strip(),
            expires_at=expires_at,
            max_uses=request.max_uses,
        )
    return CreateInviteResponse(invite=_invite_item(row), code=code)


@router.get("/admin/invites", response_model=InviteListResponse)
async def admin_list_invites(limit: int = Query(default=100, ge=1, le=500)) -> InviteListResponse:
    pool = await _require_db()
    async with pool.acquire() as conn:
        rows = await list_invites(conn, limit=limit)
    return InviteListResponse(invites=[_invite_item(row) for row in rows])


@router.post("/admin/invites/{invite_id}/revoke")
async def admin_revoke_invite(invite_id: str) -> dict[str, bool]:
    pool = await _require_db()
    async with pool.acquire() as conn:
        revoked = await revoke_invite(conn, invite_id=invite_id)
    if not revoked:
        raise HTTPException(
            status_code=404,
            detail={"code": "INVITE_NOT_FOUND", "message": "邀请不存在或已撤销。"},
        )
    return {"revoked": True}


@router.get("/admin/users", response_model=AdminUserListResponse)
async def admin_list_users(limit: int = Query(default=200, ge=1, le=500)) -> AdminUserListResponse:
    settings = get_settings()
    pool = await _require_db()
    async with pool.acquire() as conn:
        rows = await list_users(conn, limit=limit)
    return AdminUserListResponse(
        users=[
            AdminUserItem(
                id=row["id"],
                email=row["email"],
                name=row.get("name") or "",
                is_active=bool(row["is_active"]),
                is_admin=settings.is_admin_email(row["email"]),
                created_at=_iso(row["created_at"]),
            )
            for row in rows
        ]
    )


@router.post("/admin/users/{user_id}/deactivate")
async def admin_deactivate_user(user_id: str) -> dict[str, bool]:
    settings = get_settings()
    # 不允许停用自己，避免管理员误把自己锁在门外。
    if user_id == get_current_user_id():
        raise HTTPException(
            status_code=400,
            detail={"code": "CANNOT_DEACTIVATE_SELF", "message": "不能停用当前登录的管理员账号。"},
        )
    pool = await _require_db()
    async with pool.acquire() as conn:
        updated = await set_user_active(conn, user_id=user_id, is_active=False)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail={"code": "USER_NOT_FOUND", "message": "用户不存在。"},
        )
    return {"deactivated": True}


@router.post("/admin/users/{user_id}/activate")
async def admin_activate_user(user_id: str) -> dict[str, bool]:
    pool = await _require_db()
    async with pool.acquire() as conn:
        updated = await set_user_active(conn, user_id=user_id, is_active=True)
    if not updated:
        raise HTTPException(
            status_code=404,
            detail={"code": "USER_NOT_FOUND", "message": "用户不存在。"},
        )
    return {"activated": True}


def _invite_item(row: dict[str, Any]) -> InviteItem:
    return InviteItem(
        id=row["id"],
        label=row.get("label") or "",
        expires_at=_iso(row["expires_at"]) if row.get("expires_at") else None,
        max_uses=int(row["max_uses"]),
        used_count=int(row["used_count"]),
        revoked=bool(row["revoked"]),
        created_at=_iso(row["created_at"]),
    )


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

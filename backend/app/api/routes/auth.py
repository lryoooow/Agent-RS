from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.lib.auth import get_current_user_id
from app.lib.auth.security import (
    hash_password,
    hash_session_token,
    issue_session_token,
    verify_password,
)
from app.lib.db.errors import is_missing_schema_error
from app.lib.db.pool import fetch_optional_pool
from app.lib.db.repositories.identity import ensure_default_identity
from app.lib.db.repositories.auth import (
    create_session,
    create_user,
    delete_session,
    ensure_workspace_membership,
    find_user_by_email,
    get_user_by_id,
    prune_expired_sessions,
)
from app.shared.settings import get_settings

router = APIRouter(tags=["auth"])


class AuthUser(BaseModel):
    id: str
    email: str
    name: str
    authenticated: bool


class AuthMeResponse(BaseModel):
    user: AuthUser


class AuthCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1)


class RegisterRequest(AuthCredentials):
    name: str = Field(default="", max_length=80)


@router.get("/auth/me", response_model=AuthMeResponse)
async def auth_me() -> AuthMeResponse:
    settings = get_settings()
    user_id = get_current_user_id()
    pool = await fetch_optional_pool()
    user: dict[str, Any] | None = None
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                user = await get_user_by_id(conn, user_id=user_id)
        except Exception as exc:
            if not is_missing_schema_error(exc):
                raise
    if user is None:
        user = {
            "id": settings.default_user_id,
            "email": settings.default_user_email,
            "name": settings.default_user_name,
        }
    return AuthMeResponse(user=_auth_user(user, authenticated=user_id != settings.default_user_id))


@router.post("/auth/register", response_model=AuthMeResponse)
async def auth_register(request: RegisterRequest, response: Response) -> AuthMeResponse:
    settings = get_settings()
    _require_auth_settings(settings)
    email = _normalize_email(request.email)
    _validate_password(request.password, settings.auth_password_min_length)
    pool = await _require_auth_db()
    async with pool.acquire() as conn:
        try:
            async with conn.transaction():
                await ensure_default_identity(conn, settings)
                existing = await find_user_by_email(conn, email=email)
                if existing is not None:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "EMAIL_ALREADY_REGISTERED",
                            "message": "Email is already registered.",
                        },
                    )
                password_hash = await hash_password(request.password)
                user = await create_user(
                    conn,
                    email=email,
                    password_hash=password_hash,
                    name=request.name.strip() or email.split("@", 1)[0],
                )
                await ensure_workspace_membership(
                    conn,
                    workspace_id=settings.default_workspace_id,
                    user_id=user["id"],
                )
                token = issue_session_token()
                await create_session(
                    conn,
                    user_id=user["id"],
                    token_hash=hash_session_token(token, settings.auth_secret_key),
                    days=settings.auth_session_days,
                )
        except Exception as exc:
            if is_missing_schema_error(exc):
                raise _migration_required() from exc
            raise
    _set_session_cookie(response, token)
    return AuthMeResponse(user=_auth_user(user, authenticated=True))


@router.post("/auth/login", response_model=AuthMeResponse)
async def auth_login(request: AuthCredentials, response: Response) -> AuthMeResponse:
    settings = get_settings()
    _require_auth_settings(settings)
    email = _normalize_email(request.email)
    pool = await _require_auth_db()
    async with pool.acquire() as conn:
        try:
            user = await find_user_by_email(conn, email=email)
            if user is None or not user["is_active"]:
                raise _invalid_credentials()
            valid = await verify_password(request.password, user["password_hash"])
            if not valid:
                raise _invalid_credentials()
            token = issue_session_token()
            await create_session(
                conn,
                user_id=user["id"],
                token_hash=hash_session_token(token, settings.auth_secret_key),
                days=settings.auth_session_days,
            )
            await prune_expired_sessions(conn)
        except Exception as exc:
            if is_missing_schema_error(exc):
                raise _migration_required() from exc
            raise
    _set_session_cookie(response, token)
    return AuthMeResponse(user=_auth_user(user, authenticated=True))


@router.post("/auth/logout")
async def auth_logout(request: Request, response: Response) -> dict[str, bool]:
    settings = get_settings()
    token = request.cookies.get(settings.auth_session_cookie_name)
    if token:
        pool = await fetch_optional_pool()
        if pool is not None:
            async with pool.acquire() as conn:
                await delete_session(
                    conn,
                    token_hash=hash_session_token(token, settings.auth_secret_key),
                )
    response.delete_cookie(
        settings.auth_session_cookie_name,
        path="/",
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )
    return {"logged_out": True}


def _auth_user(row: dict[str, Any], *, authenticated: bool) -> AuthUser:
    return AuthUser(
        id=str(row["id"]),
        email=str(row["email"]),
        name=str(row.get("name") or ""),
        authenticated=authenticated,
    )


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        settings.auth_session_cookie_name,
        token,
        max_age=settings.auth_session_days * 24 * 60 * 60,
        path="/",
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite=settings.auth_cookie_samesite,
    )


async def _require_auth_db():
    settings = get_settings()
    if not settings.auth_enabled:
        raise HTTPException(
            status_code=404,
            detail={"code": "AUTH_DISABLED", "message": "Authentication is disabled."},
        )
    pool = await fetch_optional_pool()
    if pool is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "DATABASE_UNAVAILABLE", "message": "Database is unavailable."},
        )
    return pool


def _require_auth_settings(settings) -> None:
    if not settings.auth_secret_key:
        raise HTTPException(
            status_code=500,
            detail={"code": "AUTH_SECRET_NOT_CONFIGURED", "message": "AUTH_SECRET_KEY is not configured."},
        )


def _validate_password(password: str, min_length: int) -> None:
    if len(password) < min_length:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PASSWORD_TOO_SHORT",
                "message": f"Password must be at least {min_length} characters.",
            },
        )


def _normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_EMAIL", "message": "Email is invalid."},
        )
    return normalized


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": "INVALID_CREDENTIALS", "message": "Invalid email or password."},
    )


def _migration_required() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "DATABASE_MIGRATION_REQUIRED",
            "message": "Database schema is not up to date. Run backend/sql/apply.py and restart the backend.",
        },
    )

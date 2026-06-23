from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.auth.invites import hash_invite_code
from app.auth.security import (
    hash_password,
    hash_session_token,
    issue_session_token,
    needs_rehash,
    verify_password,
)
from app.auth.throttle import get_login_throttle
from app.db.errors import is_missing_schema_error
from app.db.pool import fetch_optional_pool
from app.db.repositories.identity import ensure_default_identity
from app.db.repositories.auth import (
    create_session,
    create_user,
    delete_session,
    ensure_workspace_membership,
    find_user_by_email,
    get_user_by_id,
    prune_expired_sessions,
    update_user_password_hash,
)
from app.db.repositories.invite import consume_invite
from app.core.settings import get_settings

router = APIRouter(tags=["auth"])

# 时序均衡用的占位哈希：登录时若用户不存在，仍对它跑一次 verify_password，
# 让"用户不存在"与"密码错误"两条路径耗时相近，消除账号枚举的时序侧信道（OWASP A07）。
# 一个固定的合法 pbkdf2 串即可（任何密码都验不过），模块加载时算一次。
_DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$AAAAAAAAAAAAAAAAAAAAAA==$"
    "x9Qe5p0m0m0m0m0m0m0m0m0m0m0m0m0m0m0m0m0m0m0="
)


class AuthUser(BaseModel):
    id: str
    email: str
    name: str
    authenticated: bool
    is_admin: bool = False


class AuthMeResponse(BaseModel):
    user: AuthUser


class AuthCredentials(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1)


class RegisterRequest(AuthCredentials):
    name: str = Field(default="", max_length=80)
    # invite_required 时必填；为空时由 auth_register 显式拒绝（不依赖 min_length 以给出明确错误码）。
    invite_code: str = Field(default="", max_length=64)


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
    return AuthMeResponse(
        user=_auth_user(
            user,
            authenticated=user_id != settings.default_user_id,
            settings=settings,
        )
    )


@router.post("/auth/register", response_model=AuthMeResponse)
async def auth_register(request: RegisterRequest, response: Response) -> AuthMeResponse:
    settings = get_settings()
    _require_auth_settings(settings)
    email = _normalize_email(request.email)
    _validate_password(request.password, settings, email=email)
    invite_code = request.invite_code.strip()
    if settings.invite_required and not invite_code:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVITE_REQUIRED", "message": "注册需要邀请码。"},
        )
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
                # 消费邀请码须在建号之后、仍在同一事务内：原子 UPDATE 占用名额，
                # 失败（无效/过期/用满/撤销）则 raise 触发整事务回滚——账号也不会落库，
                # 根治"码被消费但建号失败"或"建号成功但码未消费"的半截状态。
                if settings.invite_required:
                    code_hash = hash_invite_code(invite_code, settings.auth_secret_key)
                    consumed = await consume_invite(conn, code_hash=code_hash, user_id=user["id"])
                    if not consumed:
                        # 通用文案，不区分过期/用过/不存在，避免邀请码状态枚举。
                        raise HTTPException(
                            status_code=403,
                            detail={"code": "INVITE_INVALID", "message": "邀请码无效或已失效。"},
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
        except HTTPException:
            raise
        except Exception as exc:
            if is_missing_schema_error(exc):
                raise _migration_required() from exc
            raise
    _set_session_cookie(response, token)
    return AuthMeResponse(user=_auth_user(user, authenticated=True, settings=settings))


@router.post("/auth/login", response_model=AuthMeResponse)
async def auth_login(request: AuthCredentials, response: Response) -> AuthMeResponse:
    settings = get_settings()
    _require_auth_settings(settings)
    email = _normalize_email(request.email)
    throttle = get_login_throttle()
    retry_after = throttle.retry_after(email)
    if retry_after > 0:
        raise HTTPException(
            status_code=429,
            detail={"code": "TOO_MANY_ATTEMPTS", "message": "登录尝试过于频繁，请稍后再试。"},
            headers={"Retry-After": str(retry_after)},
        )
    pool = await _require_auth_db()
    async with pool.acquire() as conn:
        try:
            user = await find_user_by_email(conn, email=email)
            # 时序均衡：用户不存在时也跑一次 verify（对占位哈希），让两条失败路径耗时相近，
            # 再统一返回 INVALID_CREDENTIALS——不泄露"该邮箱是否注册过"（枚举防护）。
            if user is None or not user["is_active"]:
                await verify_password(request.password, _DUMMY_PASSWORD_HASH)
                throttle.record_failure(email)
                raise _invalid_credentials()
            valid = await verify_password(request.password, user["password_hash"])
            if not valid:
                throttle.record_failure(email)
                raise _invalid_credentials()
            # 登录成功：清限流计数；若旧哈希工作因子偏低，用当前参数重哈希落库（透明升级，防复发）。
            throttle.reset(email)
            if needs_rehash(user["password_hash"]):
                new_hash = await hash_password(request.password)
                await update_user_password_hash(conn, user_id=user["id"], password_hash=new_hash)
            token = issue_session_token()
            await create_session(
                conn,
                user_id=user["id"],
                token_hash=hash_session_token(token, settings.auth_secret_key),
                days=settings.auth_session_days,
            )
            await prune_expired_sessions(conn)
        except HTTPException:
            raise
        except Exception as exc:
            if is_missing_schema_error(exc):
                raise _migration_required() from exc
            raise
    _set_session_cookie(response, token)
    return AuthMeResponse(user=_auth_user(user, authenticated=True, settings=settings))


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


def _auth_user(row: dict[str, Any], *, authenticated: bool, settings=None) -> AuthUser:
    settings = settings or get_settings()
    email = str(row["email"])
    return AuthUser(
        id=str(row["id"]),
        email=email,
        name=str(row.get("name") or ""),
        authenticated=authenticated,
        # 管理员判定只在已认证用户上有意义：默认用户/未登录恒为 false。
        is_admin=authenticated and settings.is_admin_email(email),
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
    if settings.database_enabled and settings.auth_secret_key == "dev-change-me":
        raise HTTPException(
            status_code=500,
            detail={"code": "AUTH_SECRET_INSECURE", "message": "AUTH_SECRET_KEY must be changed."},
        )


def _validate_password(password: str, settings, *, email: str) -> None:
    min_length = settings.auth_password_min_length
    max_length = settings.auth_password_max_length
    if len(password) < min_length:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PASSWORD_TOO_SHORT",
                "message": f"Password must be at least {min_length} characters.",
            },
        )
    # 上限防超长密码触发 PBKDF2 大量计算的 DoS（OWASP 建议设上限且不静默截断）。
    if len(password) > max_length:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PASSWORD_TOO_LONG",
                "message": f"Password must be at most {max_length} characters.",
            },
        )
    # 拒绝密码包含邮箱本地名（如 alice@x.com 用 alice123）——低强度可猜。
    local_part = email.split("@", 1)[0]
    if len(local_part) >= 3 and local_part in password.lower():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PASSWORD_TOO_WEAK",
                "message": "Password must not contain your email name.",
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

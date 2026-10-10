from __future__ import annotations

from typing import Any

from asyncpg import UniqueViolationError
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.auth import get_current_user_id
from app.auth.security import (
    hash_password,
    hash_session_token,
    issue_session_token,
    is_secure_auth_secret,
    needs_rehash,
    verify_password,
)
from app.db.errors import is_missing_schema_error
from app.auth.rate_limit import get_auth_rate_limiter
from app.db.pool import fetch_optional_pool
from app.db.repositories.identity import ensure_default_identity
from app.db.repositories.auth import (
    create_session,
    create_user,
    delete_session,
    ensure_workspace_membership,
    find_user_by_email,
    get_user_by_id,
    lock_user_for_login,
    limit_user_sessions,
    prune_expired_sessions,
    update_user_password_hash,
)
from app.core.settings import get_settings

router = APIRouter(tags=["auth"])

# Reserved platform account; privilege still depends on server-configured user IDs.
ADMIN_LOGIN_EMAIL = "admin@local.agent-rs"

# 时序均衡用的占位哈希：登录时若用户不存在，仍对它跑一次 verify_password，
# 让"用户不存在"与"密码错误"两条路径耗时相近，消除账号枚举的时序侧信道（OWASP A07）。
# 使用离线生成的真实 PBKDF2 记录；验证路径仍执行完整 600k 次计算。
_DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$mei5ZRZkf7lQUlIrzWJ3Rw==$"
    "z1wg1i+xT+E7j9L2EK/AmTJn/IqNI9tPNa9VV8Xq8lA="
)

# 小而确定的高频弱密码集合。这里不强制“大写+小写+数字+符号”的组成规则，
# 以免拒绝更长、更容易记住的口令；改为拦截可直接猜中的常见口令和重复字符。
# 比对前会移除空格/常见分隔符，因此 Password-123 也不会绕过。
_COMMON_PASSWORDS = frozenset(
    {
        "1234567890",
        "abcdefghij",
        "administrator",
        "letmein123",
        "password",
        "password123",
        "qwerty12345",
        "qwertyuiop",
        "welcome123",
    }
)


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


def _client_key(request: Request) -> str:
    # Uvicorn only trusts forwarding headers from the local Cloudflare tunnel.
    # Direct clients therefore cannot spoof this address with X-Forwarded-For.
    return request.client.host if request.client else "unknown"


def _raise_rate_limited(retry_after: int) -> None:
    raise HTTPException(
        status_code=429,
        detail={
            "code": "AUTH_RATE_LIMITED",
            "message": "Too many authentication attempts. Please try again later.",
        },
        headers={"Retry-After": str(max(1, retry_after))},
    )


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
async def auth_register(
    payload: RegisterRequest,
    response: Response,
    client_key: str = Depends(_client_key),
) -> AuthMeResponse:
    settings = get_settings()
    _require_auth_settings(settings)
    limiter = get_auth_rate_limiter(settings)
    retry_after = await limiter.check_register(client_key=client_key)
    if retry_after is not None:
        _raise_rate_limited(retry_after)
    email = _normalize_registration_email(payload.email)
    _validate_password(payload.password, settings, email=email)
    pool = await _require_auth_db()
    password_hash = await hash_password(payload.password)
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
                user = await create_user(
                    conn,
                    email=email,
                    password_hash=password_hash,
                    name=payload.name.strip() or email.split("@", 1)[0],
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
                await limit_user_sessions(
                    conn,
                    user_id=user["id"],
                    keep=settings.auth_max_active_sessions_per_user,
                )
        except HTTPException:
            raise
        except UniqueViolationError as exc:
            if exc.constraint_name != "idx_users_email_unique":
                raise
            # Two registrations can both observe absence before the unique
            # constraint decides which one wins. Keep the normal 409 response.
            raise HTTPException(status_code=409, detail={"code": "EMAIL_ALREADY_REGISTERED", "message": "Email is already registered."}) from exc
        except Exception as exc:
            if is_missing_schema_error(exc):
                raise _migration_required() from exc
            raise
    _set_session_cookie(response, token)
    return AuthMeResponse(user=_auth_user(user, authenticated=True, settings=settings))


@router.post("/auth/login", response_model=AuthMeResponse)
async def auth_login(
    payload: AuthCredentials,
    response: Response,
    client_key: str = Depends(_client_key),
) -> AuthMeResponse:
    settings = get_settings()
    _require_auth_settings(settings)
    email = _normalize_login_identifier(payload.email)
    limiter = get_auth_rate_limiter(settings)
    retry_after = await limiter.check_login(account_key=email, client_key=client_key)
    if retry_after is not None:
        _raise_rate_limited(retry_after)
    pool = await _require_auth_db()
    try:
        async with pool.acquire() as conn:
            user = await find_user_by_email(conn, email=email)
        for _ in range(2):
            # 时序均衡：用户不存在时也跑一次 verify（对占位哈希），让两条失败路径耗时相近。
            if (user is None or not user["is_active"] or not user.get("password_hash")
                    or (email == ADMIN_LOGIN_EMAIL and not settings.is_admin_user_id(str(user["id"])) )):
                await verify_password(payload.password, _DUMMY_PASSWORD_HASH)
                await limiter.record_login_failure(account_key=email)
                raise _invalid_credentials()
            valid = await verify_password(payload.password, user["password_hash"])
            if not valid:
                await limiter.record_login_failure(account_key=email)
                raise _invalid_credentials()
            # 登录成功：若旧哈希工作因子偏低，用当前参数重哈希落库（透明升级）。
            # 慢操作 hash_password 在事务外算，避免占着连接；三个写（rehash/session/prune）
            # 包进同一事务，与 register 对齐——任一失败整体回滚，不残留半套（P2-10）。
            new_hash = (
                await hash_password(payload.password)
                if needs_rehash(user["password_hash"])
                else None
            )
            async with pool.acquire() as conn:
                async with conn.transaction():
                    current = await lock_user_for_login(conn, user_id=user["id"])
                    if current is None:
                        raise _invalid_credentials()
                    if current["password_hash"] != user["password_hash"]:
                        # Includes concurrent transparent rehash. Revalidate
                        # the new snapshot outside the connection, at most once.
                        user = current
                        continue
                    user = current
                    if new_hash is not None:
                        await update_user_password_hash(conn, user_id=user["id"], password_hash=new_hash)
                    token = issue_session_token()
                    await create_session(
                        conn, user_id=user["id"],
                        token_hash=hash_session_token(token, settings.auth_secret_key),
                        days=settings.auth_session_days,
                    )
                    await prune_expired_sessions(conn)
                    await limit_user_sessions(conn, user_id=user["id"], keep=settings.auth_max_active_sessions_per_user)
                break
        else:
            raise _invalid_credentials()
        await limiter.record_login_success(account_key=email)
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
    if not is_secure_auth_secret(settings.auth_secret_key):
        raise HTTPException(
            status_code=500,
            detail={
                "code": "AUTH_SECRET_INSECURE",
                "message": "AUTH_SECRET_KEY must be a non-default value of at least 32 characters.",
            },
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
    normalized = "".join(char for char in password.casefold() if char.isalnum())
    if normalized in _COMMON_PASSWORDS or len(set(normalized)) <= 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PASSWORD_TOO_COMMON",
                "message": "Password is too common or easy to guess.",
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


def _normalize_login_identifier(identifier: str) -> str:
    if identifier.strip().lower() == "admin":
        return ADMIN_LOGIN_EMAIL
    return _normalize_email(identifier)


def _normalize_registration_email(email: str) -> str:
    normalized = _normalize_email(email)
    if normalized == ADMIN_LOGIN_EMAIL:
        raise HTTPException(status_code=422, detail={"code": "RESERVED_ACCOUNT", "message": "This account is reserved for platform administration."})
    return normalized


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

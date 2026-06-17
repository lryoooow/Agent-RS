from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.agent.embedding.service import get_embedding_service
from app.agent.errors import AIError
from app.auth import reset_current_user_id, set_current_user_id
from app.auth.session import AuthSessionUnavailable, get_session_user
from app.db.pool import close_db_pool, fetch_optional_pool, init_db_pool
from app.db.repositories.identity import ensure_default_identity
from app.documents.task_registry import recover_document_jobs, shutdown_tasks
from app.core.logging import configure_logging
from app.core.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db_pool()
    await _seed_default_identity()
    await recover_document_jobs()
    settings = get_settings()
    embedding_service = get_embedding_service()
    if settings.storage_active and embedding_service.available:
        await embedding_service.ping()
    try:
        yield
    finally:
        await shutdown_tasks()
        await close_db_pool()


async def _seed_default_identity() -> None:
    """SQLite 后端启动时预置默认用户/工作区。

    conversations.created_by_user_id 对 users 有外键，且 SQLite PRAGMA
    foreign_keys=ON 会强校验；预置后，DB 关闭鉴权下的默认用户首条会话才能落库。
    Postgres 路径维持原有惰性 seed（register/首条 chat 内），不在此重复。
    """
    settings = get_settings()
    if settings.resolved_storage_backend != "sqlite":
        return
    pool = await fetch_optional_pool()
    if pool is None:
        return
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await ensure_default_identity(conn, settings)
    except Exception:
        logging.getLogger(__name__).exception("Failed to seed default identity for SQLite backend.")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(title="Agent-RS API", version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix="/api")

    @app.middleware("http")
    async def bind_current_user(request, call_next):
        content_type = request.headers.get("content-type", "")
        content_length = request.headers.get("content-length")
        try:
            request_size = int(content_length) if content_length else 0
        except ValueError:
            request_size = 0
        if (
            request_size
            and "multipart/form-data" not in content_type
            and request_size > settings.max_json_body_bytes
        ):
            return JSONResponse(
                status_code=413,
                content={"error": {"code": "REQUEST_TOO_LARGE", "message": "Request body is too large."}},
            )
        # Read the old cookie name during the Agent-RS rename migration.
        session_token = request.cookies.get(settings.auth_session_cookie_name) or request.cookies.get("chatbot_session")
        try:
            user = await get_session_user(session_token)
        except AuthSessionUnavailable:
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "AUTH_SESSION_UNAVAILABLE",
                        "message": "Session authentication is temporarily unavailable.",
                    }
                },
            )
        context_token = set_current_user_id(user["id"] if user else settings.default_user_id)
        try:
            response = await call_next(request)
            response.headers.setdefault("X-Content-Type-Options", "nosniff")
            response.headers.setdefault("X-Frame-Options", "DENY")
            response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "img-src 'self' data: blob:; "
                "style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; "
                "connect-src 'self' http://localhost:3000 http://127.0.0.1:3000; "
                "worker-src 'self' blob:; "
                "object-src 'none'; "
                "base-uri 'self'; "
                "frame-ancestors 'none'",
            )
            if settings.auth_cookie_secure:
                response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            return response
        finally:
            reset_current_user_id(context_token)

    @app.exception_handler(AIError)
    async def handle_ai_error(_, exc: AIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Invalid request payload.",
                    "details": exc.errors(),
                }
            },
        )

    return app


app = create_app()

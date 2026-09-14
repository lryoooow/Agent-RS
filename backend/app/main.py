from contextlib import asynccontextmanager

import logging
import time
import uuid

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router as api_router
from app.agent.embedding.service import get_embedding_service
from app.agent.errors import AIError
from app.agent.geocode import aclose_geocode_client
from app.agent.persistence import drain_persistence_tasks
from app.agent.tool_jobs import start_tool_job_worker, stop_tool_job_worker
from app.auth import get_current_user_id, reset_current_user_id, set_current_user_id
from app.auth.session import AuthSessionUnavailable, get_session_user
from app.db.pool import close_db_pool, fetch_optional_pool, init_db_pool
from app.documents.task_registry import recover_document_jobs, shutdown_tasks
from app.core.logging import configure_logging
from app.core.settings import get_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db_pool()
    await _verify_database_connection()
    await _ensure_object_storage_ready()
    await recover_document_jobs()
    start_tool_job_worker()
    settings = get_settings()
    _warn_missing_ai_credentials(settings)
    embedding_service = get_embedding_service()
    if settings.storage_active and embedding_service.available:
        await embedding_service.ping()
    try:
        yield
    finally:
        await stop_tool_job_worker()
        await shutdown_tasks()
        await drain_persistence_tasks()  # O1: 排空 embedding/memory 后台任务（须在关池前）
        await aclose_geocode_client()  # O5: 关闭模块全局 httpx 客户端
        await close_db_pool()


def _warn_missing_ai_credentials(settings) -> None:
    """启动时提示凭据缺口，而不是等到第一次聊天请求才 500。

    AI_API_KEY 为空且不允许前端覆盖时，任何 /api/chat 都会以 ConfigError 失败；
    允许前端覆盖时降级为提示（用户可以在设置页填 key）。
    """
    if settings.ai_api_key:
        return
    if settings.allow_client_provider_config:
        logger.warning("AI_API_KEY 未配置；请在浏览器设置页填写，否则聊天请求会失败")
    else:
        logger.warning(
            "AI_API_KEY 未配置且 ALLOW_CLIENT_PROVIDER_CONFIG=false——"
            "所有聊天请求都将失败，请配置 AI_API_KEY 后重启"
        )


async def _verify_database_connection() -> None:
    settings = get_settings()
    if not settings.database_enabled:
        return

    pool = await fetch_optional_pool()
    if pool is None:
        raise RuntimeError("DATABASE_ENABLED=true 但连接池未就绪；后端拒绝启动。")
    async with pool.acquire() as conn:
        await conn.execute("SELECT 1")


async def _ensure_object_storage_ready() -> None:
    """minio 后端：启动时幂等建桶，免手动 mc。本地后端无需任何操作。

    失败只告警不阻断启动（与 schema 迁移同策略）：MinIO 刚拉起尚未就绪等场景，
    由后续上传/读取按需重试；本地后端则压根不会走到这里的建桶分支。
    """
    settings = get_settings()
    if settings.storage_backend.strip().lower() != "minio":
        return
    try:
        from app.storage.object_store import get_object_store

        store = get_object_store()
        ensure_bucket = getattr(store, "ensure_bucket", None)
        if ensure_bucket is not None:
            await ensure_bucket()
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "MinIO 桶初始化失败；确认 MinIO 已启动并检查 MINIO_* 配置。"
        )


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
        # P3 可观测性：请求 ID（透传或生成）+ 完成日志（method/path/status/
        # duration/user）。工具审计日志（tool.invoke）自此可与 HTTP 流量按
        # request_id 关联；替代 uvicorn 噪声 access log 的关键信息。
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        started = time.perf_counter()
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
            response.headers["X-Request-ID"] = request_id
            logger.info(
                "http.request id=%s method=%s path=%s status=%s duration_ms=%d user=%s",
                request_id,
                request.method,
                request.url.path,
                response.status_code,
                (time.perf_counter() - started) * 1000,
                get_current_user_id() or "<anonymous>",
            )
            return response
        except Exception:
            logger.exception(
                "http.request id=%s method=%s path=%s failed duration_ms=%d",
                request_id,
                request.method,
                request.url.path,
                (time.perf_counter() - started) * 1000,
            )
            raise
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
                    # ctx 里可能带 ValueError 等异常对象（model_validator 抛出），
                    # 直接 json 序列化会 500；统一字符串化。
                    "details": [
                        {**error, "ctx": {k: str(v) for k, v in error.get("ctx", {}).items()}}
                        if error.get("ctx")
                        else error
                        for error in exc.errors()
                    ],
                }
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_, exc: StarletteHTTPException) -> JSONResponse:
        """HTTPException → 唯一错误信封（app/api/errors.py 的契约）。

        - detail 是 {code, message}（api_error 抛出）：原样包进 error 键；
        - detail 是裸字符串（存量写法，逐步迁移中）：补 ``HTTP_<status>`` 机器码；
        - 其它形态：字符串化兜底，绝不输出第二种顶层形状。
        """
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail and "message" in detail:
            payload = {"code": str(detail["code"]), "message": str(detail["message"])}
            extra = {k: v for k, v in detail.items() if k not in ("code", "message")}
            if extra:
                payload.update(extra)
        elif isinstance(detail, str):
            payload = {"code": f"HTTP_{exc.status_code}", "message": detail}
        else:
            payload = {"code": f"HTTP_{exc.status_code}", "message": str(detail)}
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": payload},
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request, exc: Exception) -> JSONResponse:
        """兜底 500：不向客户端泄任何内部信息，细节只进日志。

        没有 handler 时 FastAPI/Starlette 会返回 {"detail": "Internal Server Error"}
        ——第三种错误形状；且 TestClient 场景下异常会直接抛出掩盖真实响应。
        """
        logger.exception(
            "未处理异常 path=%s method=%s type=%s",
            request.url.path,
            request.method,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR", "message": "服务器内部错误，请稍后重试。"}},
        )

    return app


app = create_app()

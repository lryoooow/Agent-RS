from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router as api_router
from app.lib.ai.embedding.service import get_embedding_service
from app.lib.ai.errors import AIError
from app.lib.auth import reset_current_user_id, set_current_user_id
from app.lib.auth.session import get_session_user
from app.lib.db.pool import close_db_pool, init_db_pool
from app.lib.documents.task_registry import recover_document_jobs, shutdown_tasks
from app.shared.logging import configure_logging
from app.shared.settings import get_settings


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db_pool()
    await recover_document_jobs()
    settings = get_settings()
    embedding_service = get_embedding_service()
    if settings.database_enabled and embedding_service.available:
        await embedding_service.ping()
    try:
        yield
    finally:
        await shutdown_tasks()
        await close_db_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(title="Chatbot API", version="0.1.0", lifespan=lifespan)

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
        session_token = request.cookies.get(settings.auth_session_cookie_name)
        user = await get_session_user(session_token)
        context_token = set_current_user_id(user["id"] if user else settings.default_user_id)
        try:
            return await call_next(request)
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

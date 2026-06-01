from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.config import router as config_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.memories import router as memories_router

router = APIRouter()
router.include_router(health_router)
router.include_router(config_router)
router.include_router(auth_router)
router.include_router(chat_router)
router.include_router(documents_router)
router.include_router(conversations_router)
router.include_router(memories_router)

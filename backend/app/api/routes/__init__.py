from fastapi import APIRouter, Depends

from app.api.deps import require_authenticated_user
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.config import router as config_router
from app.api.routes.conversations import router as conversations_router
from app.api.routes.documents import router as documents_router
from app.api.routes.health import router as health_router
from app.api.routes.imagery import router as imagery_router
from app.api.routes.memories import router as memories_router
from app.api.routes.report import router as report_router

router = APIRouter()

# 开放路由：无需登录。health/config 给前端启动探测，auth 是登录入口本身。
router.include_router(health_router)
router.include_router(config_router)
router.include_router(auth_router)

# 数据类路由：统一挂强制登录依赖（auth_required 时未登录→401）。
# 把"必须登录"落到服务端，绕过前端 UI 直接打接口同样被拦。
_auth_dep = [Depends(require_authenticated_user)]
router.include_router(chat_router, dependencies=_auth_dep)
router.include_router(documents_router, dependencies=_auth_dep)
router.include_router(conversations_router, dependencies=_auth_dep)
router.include_router(memories_router, dependencies=_auth_dep)
router.include_router(imagery_router, dependencies=_auth_dep)
router.include_router(report_router, dependencies=_auth_dep)

# 管理路由：自带 require_admin 依赖（见 admin.py），无需在此重复挂。
router.include_router(admin_router)

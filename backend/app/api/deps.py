from fastapi import HTTPException

from app.auth import get_current_user_id
from app.core.settings import get_settings
from app.db.errors import is_missing_schema_error
from app.db.pool import fetch_optional_pool
from app.db.repositories.auth import get_user_by_id
from app.services.chat_service import ChatService


def get_chat_service() -> ChatService:
    return ChatService()


async def require_authenticated_user() -> str:
    """强制登录依赖：auth_required 为真时，未登录（解析为默认用户）一律 401。

    挂在数据类路由（chat/conversations/documents/memories/imagery/report）上，
    把"必须登录"落到服务端，而非只靠前端 UI 拦截（绕过 UI 直接打接口也会被拒）。
    auth_required 为假（本地 DB 关闭）时放行默认用户，保留零依赖开发路径。
    返回当前 user_id，供需要的路由直接复用。
    """
    settings = get_settings()
    user_id = get_current_user_id()
    if settings.auth_required and user_id == settings.default_user_id:
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTHENTICATION_REQUIRED", "message": "请先登录。"},
        )
    return user_id


async def require_admin() -> dict:
    """管理员依赖：解析当前用户，邮箱∈admin_emails 才放行，否则 403。

    先经 require_authenticated_user 的等价校验（未登录→401），再查库取邮箱比对名单。
    返回用户行，供管理路由按需使用。
    """
    settings = get_settings()
    user_id = await require_authenticated_user()
    pool = await fetch_optional_pool()
    user: dict | None = None
    if pool is not None:
        try:
            async with pool.acquire() as conn:
                user = await get_user_by_id(conn, user_id=user_id)
        except Exception as exc:
            if not is_missing_schema_error(exc):
                raise
    if user is None or not settings.is_admin_email(user.get("email")):
        raise HTTPException(
            status_code=403,
            detail={"code": "ADMIN_REQUIRED", "message": "需要管理员权限。"},
        )
    return user

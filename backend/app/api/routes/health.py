import shutil

from fastapi import APIRouter

from app.core.paths import imagery_root
from app.core.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    storage_ok = _storage_writable()
    docker_available = shutil.which("docker") is not None
    return {
        "ok": storage_ok,
        "api_key_configured": bool(settings.ai_api_key.strip()),
        "web_search_configured": bool(settings.tavily_api_key.strip()),
        "storage_writable": storage_ok,
        "docker_available": docker_available,
        "ndvi_mcp": {
            "use_docker": settings.ndvi_mcp_use_docker,
            "image": settings.ndvi_mcp_image,
            "allow_local_fallback": settings.ndvi_mcp_allow_local_fallback,
            "docker_command_available": docker_available,
        },
    }


def _storage_writable() -> bool:
    try:
        root = imagery_root(create=True)
        probe = root / ".healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False

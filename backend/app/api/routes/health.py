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
        "rs_tools_mcp": _mcp_status(
            use_docker=settings.rs_tools_mcp_use_docker,
            image=settings.rs_tools_mcp_image,
            docker_available=docker_available,
        ),
        "rs_detect_mcp": _mcp_status(
            use_docker=settings.rs_detect_mcp_use_docker,
            image=settings.rs_detect_mcp_image,
            docker_available=docker_available,
        ),
        "rs_segment_mcp": _mcp_status(
            use_docker=settings.rs_segment_mcp_use_docker,
            image=settings.rs_segment_mcp_image,
            docker_available=docker_available,
        ),
        "rs_doc_mcp": _mcp_status(
            use_docker=settings.rs_doc_mcp_use_docker,
            image=settings.rs_doc_mcp_image,
            docker_available=docker_available,
        ),
    }


def _mcp_status(*, use_docker: bool, image: str, docker_available: bool) -> dict:
    return {
        "use_docker": use_docker,
        "image": image,
        "docker_command_available": docker_available,
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

import shutil
import asyncio
import subprocess
import time
from functools import lru_cache

import httpx

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.paths import imagery_root
from app.core.settings import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> JSONResponse:
    """健康探测。存储不可写时返回 503——状态码即真相，监控按码报警。

    （此前 ok=false 仍返 200，探活探针会放过故障。）
    """
    settings = get_settings()
    images = (settings.rs_tools_mcp_image, settings.rs_detect_mcp_image, settings.rs_doc_mcp_image)
    presence = await asyncio.gather(*(asyncio.to_thread(_image_present, name, int(time.monotonic() // 30)) for name in images))
    sam3 = await _sam3_status(settings.sam3_service_url, settings.sam3_enabled)
    storage_ok = _storage_writable()
    payload = {
        "ok": storage_ok,
        "api_key_configured": bool(settings.ai_api_key.strip()),
        "web_search_configured": bool(settings.tavily_api_key.strip()),
        "storage_writable": storage_ok,
        "docker_available": shutil.which("docker") is not None,
        "rs_tools_mcp": _mcp_status(
            use_docker=settings.rs_tools_mcp_use_docker,
            image=settings.rs_tools_mcp_image,
            docker_available=shutil.which("docker") is not None,
        ),
        "rs_detect_mcp": _mcp_status(
            use_docker=settings.rs_detect_mcp_use_docker,
            image=settings.rs_detect_mcp_image,
            docker_available=shutil.which("docker") is not None,
        ),
        "sam3": sam3,
        "rs_doc_mcp": _mcp_status(
            use_docker=settings.rs_doc_mcp_use_docker,
            image=settings.rs_doc_mcp_image,
            docker_available=shutil.which("docker") is not None,
        ),
    }
    for name, present in zip(("rs_tools_mcp", "rs_detect_mcp", "rs_doc_mcp"), presence):
        payload[name]["image_present"] = present
        payload[name]["ready"] = bool(payload[name]["use_docker"] and present)
    return JSONResponse(status_code=200 if storage_ok else 503, content=payload)


@lru_cache(maxsize=32)
def _image_present(image: str, _time_bucket: int) -> bool:
    try:
        return subprocess.run(["docker", "image", "inspect", image], stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=3, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _mcp_status(*, use_docker: bool, image: str, docker_available: bool) -> dict:
    return {
        "use_docker": use_docker,
        "image": image,
        "docker_command_available": docker_available,
    }


async def _sam3_status(url: str, enabled: bool) -> dict:
    if not enabled:
        return {"enabled": False, "ready": False, "model": "SAM3"}
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            response = await client.get(f"{url.rstrip('/')}/health")
            response.raise_for_status()
            payload = response.json()
        return {"enabled": True, "ready": payload.get("status") == "ok", **payload}
    except Exception:
        return {"enabled": True, "ready": False, "model": "SAM3"}


def _storage_writable() -> bool:
    try:
        root = imagery_root(create=True)
        probe = root / ".healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False

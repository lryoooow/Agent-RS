import asyncio
import shutil
import subprocess
import time
from functools import lru_cache

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.api.deps import require_authenticated_user
from app.core.paths import imagery_root
from app.core.settings import get_settings
from app.db.pool import fetch_optional_pool

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> JSONResponse:
    """Minimal public readiness response without infrastructure disclosure."""
    storage_ok, database_ok = await asyncio.gather(
        asyncio.to_thread(_storage_writable),
        _database_healthy(),
    )
    ok = storage_ok and database_ok
    return JSONResponse(
        status_code=200 if ok else 503,
        content={"ok": ok, "status": "ok" if ok else "unavailable"},
    )


@router.get(
    "/health/details",
    dependencies=[Depends(require_authenticated_user)],
)
async def health_details() -> JSONResponse:
    """Authenticated diagnostics used by operators and the platform UI."""
    settings = get_settings()
    images = (
        settings.rs_tools_mcp_image,
        settings.rs_detect_mcp_image,
        settings.rs_doc_mcp_image,
    )
    presence, sam3, storage_ok, database_ok = await asyncio.gather(
        asyncio.gather(
            *(
                asyncio.to_thread(
                    _image_present,
                    name,
                    int(time.monotonic() // 30),
                )
                for name in images
            )
        ),
        _sam3_status(settings.sam3_service_url, settings.sam3_enabled),
        asyncio.to_thread(_storage_writable),
        _database_healthy(),
    )
    ok = storage_ok and database_ok
    docker_available = shutil.which("docker") is not None
    payload = {
        "ok": ok,
        "storage_writable": storage_ok,
        "database_ready": database_ok,
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
        "sam3": sam3,
        "rs_doc_mcp": _mcp_status(
            use_docker=settings.rs_doc_mcp_use_docker,
            image=settings.rs_doc_mcp_image,
            docker_available=docker_available,
        ),
    }
    for name, present in zip(
        ("rs_tools_mcp", "rs_detect_mcp", "rs_doc_mcp"),
        presence,
    ):
        payload[name]["image_present"] = present
        payload[name]["ready"] = bool(payload[name]["use_docker"] and present)
    return JSONResponse(status_code=200 if ok else 503, content=payload)


@lru_cache(maxsize=32)
def _image_present(image: str, _time_bucket: int) -> bool:
    try:
        return subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        ).returncode == 0
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
        return {
            "enabled": True,
            "ready": payload.get("status") == "ok",
            **payload,
        }
    except Exception:
        return {"enabled": True, "ready": False, "model": "SAM3"}


async def _database_healthy() -> bool:
    settings = get_settings()
    if not settings.database_enabled:
        return True

    async def probe() -> bool:
        pool = await fetch_optional_pool()
        if pool is None:
            return False
        async with pool.acquire() as conn:
            return await conn.fetchval("SELECT 1") == 1

    try:
        return await asyncio.wait_for(probe(), timeout=1.5)
    except Exception:
        return False


def _storage_writable() -> bool:
    try:
        root = imagery_root(create=True)
        probe = root / ".healthcheck"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False

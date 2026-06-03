import asyncio
import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from app.lib.ai.agents.tools.ndvi.formatter import format_ndvi_context
from app.lib.ai.agents.tools.ndvi.schema import NDVIArguments
from app.lib.ai.agents.types import ToolRunResult
from app.lib.ai.mcp.ndvi_client import MCPCallError, NDVIMCPClient
from app.schemas.chat import ToolExecutionInfo
from app.shared.paths import imagery_root, project_root
from app.shared.settings import get_settings

logger = logging.getLogger(__name__)

COMPUTE_SCRIPT = project_root() / "docker" / "ndvi" / "compute_ndvi.py"


class NDVIExecutionError(Exception):
    def __init__(self, message: str, code: str = "ndvi_execution_failed") -> None:
        super().__init__(message)
        self.code = code


def _imagery_root() -> Path:
    return imagery_root()


async def run_ndvi(args: NDVIArguments) -> ToolRunResult:
    settings = get_settings()
    imagery_dir = _imagery_root() / args.imagery_id
    source_path = imagery_dir / "working.tif"
    if not source_path.exists():
        source_path = imagery_dir / "source.tif"

    if not source_path.exists():
        return ToolRunResult(
            tool_context=f"影像 {args.imagery_id} 不存在，请先上传影像。",
            error="imagery_not_found",
            metadata={"error_code": "imagery_not_found", "execution_mode": "failed"},
        )

    band_error = _validate_bands(source_path, args.red_band, args.nir_band)
    if band_error:
        return ToolRunResult(
            tool_context=f"NDVI 计算参数无效: {band_error}",
            error="invalid_bands",
            metadata={"error_code": "invalid_bands", "execution_mode": "failed"},
        )

    output_dir = imagery_dir / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    start = perf_counter()
    try:
        stats, execution = await _run_ndvi_execution(source_path, output_dir, args, settings)
    except (asyncio.TimeoutError, subprocess.TimeoutExpired):
        return _error_result("NDVI 计算超时，请稍后重试。", "docker_timeout")
    except NDVIExecutionError as exc:
        return _error_result(f"NDVI 计算失败: {exc}", exc.code)
    except FileNotFoundError:
        logger.error("Docker command not found. Is Docker installed and in PATH?")
        return _error_result(
            "NDVI 计算失败: Docker 未安装或不在系统 PATH 中，请确认 Docker 已安装并启动。",
            "docker_not_found",
        )
    except Exception as exc:
        logger.exception("NDVI unexpected error: %s", exc)
        return _error_result(f"NDVI 计算失败: {exc}", "unexpected_error")

    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info(
        "NDVI completed: imagery=%s, mode=%s, fallback=%s, elapsed=%sms",
        args.imagery_id,
        execution["mode"],
        execution["fallback_used"],
        elapsed_ms,
    )

    result_filename = "ndvi_colored.png"
    tool_context = format_ndvi_context(args.imagery_id, stats, result_filename)
    bounds = _read_bounds(imagery_dir / "metadata.json")

    execution_info = ToolExecutionInfo(
        mode=execution["mode"],
        fallback_used=execution["fallback_used"],
        error_code=execution.get("error_code"),
    )
    geospatial_result = {
        "type": "ndvi",
        "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{result_filename}",
        "bounds": bounds,
        "stats": stats,
        "execution": execution_info.model_dump(exclude_none=True),
    }

    return ToolRunResult(
        tool_context=tool_context,
        result_count=1,
        query=f"NDVI({args.imagery_id})",
        geospatial_result=geospatial_result,
        metadata={
            "execution_mode": execution["mode"],
            "fallback_used": execution["fallback_used"],
            "error_code": execution.get("error_code"),
        },
    )


def _error_result(message: str, code: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=message,
        error=code,
        metadata={"error_code": code, "execution_mode": "failed"},
    )


def _read_bounds(meta_path: Path) -> tuple[float, float, float, float] | None:
    if not meta_path.exists():
        return None
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Invalid imagery metadata JSON: %s", meta_path, exc_info=True)
        return None
    bounds = meta.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 4:
        return None
    try:
        return tuple(float(value) for value in bounds)  # type: ignore[return-value]
    except (TypeError, ValueError):
        return None


def _validate_bands(source_path: Path, red_band: int, nir_band: int) -> str | None:
    import rasterio

    if red_band < 1 or nir_band < 1:
        return f"波段索引必须从 1 开始，当前 red={red_band}, nir={nir_band}"
    with rasterio.open(source_path) as src:
        if red_band > src.count or nir_band > src.count:
            return f"影像只有 {src.count} 个波段，当前 red={red_band}, nir={nir_band}"
    return None


def _run_ndvi_sync(source_path: Path, output_dir: Path, args: NDVIArguments, settings) -> dict[str, Any]:
    env = {
        "RED_BAND": str(args.red_band),
        "NIR_BAND": str(args.nir_band),
        "INPUT_PATH": str(source_path.resolve()),
        "OUTPUT_DIR": str(output_dir.resolve()),
    }
    run_env = {**os.environ, **env}

    result = subprocess.run(
        [sys.executable, str(COMPUTE_SCRIPT)],
        capture_output=True,
        timeout=settings.ndvi_docker_timeout_seconds,
        env=run_env,
    )
    if result.returncode != 0:
        error_msg = result.stderr.decode(errors="replace").strip()[:500]
        raise NDVIExecutionError(error_msg or f"exit code {result.returncode}", "local_subprocess_failed")

    stats_path = output_dir / "stats.json"
    if not stats_path.exists():
        raise NDVIExecutionError("计算脚本未生成 stats.json", "missing_stats")

    return json.loads(stats_path.read_text(encoding="utf-8"))


async def _run_ndvi_execution(
    source_path: Path,
    output_dir: Path,
    args: NDVIArguments,
    settings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if settings.ndvi_mcp_use_docker:
        try:
            client = NDVIMCPClient(
                image=settings.ndvi_mcp_image,
                host_imagery_root=_imagery_root(),
                container_imagery_root="/data",
                timeout_seconds=settings.ndvi_docker_timeout_seconds,
                memory_limit=settings.ndvi_mcp_memory_limit,
                cpus=settings.ndvi_mcp_cpus,
                network=settings.ndvi_mcp_network,
            )
            stats = await client.call_ndvi(
                source_path=source_path,
                output_dir=output_dir,
                red_band=args.red_band,
                nir_band=args.nir_band,
            )
            return stats, {"mode": "docker_mcp", "fallback_used": False, "error_code": None}
        except FileNotFoundError as exc:
            return await _handle_docker_failure(exc, "docker_not_found", source_path, output_dir, args, settings)
        except asyncio.TimeoutError as exc:
            return await _handle_docker_failure(exc, "mcp_timeout", source_path, output_dir, args, settings)
        except MCPCallError as exc:
            return await _handle_docker_failure(exc, "mcp_error", source_path, output_dir, args, settings)
        except Exception as exc:
            return await _handle_docker_failure(exc, "mcp_error", source_path, output_dir, args, settings)

    stats = await asyncio.to_thread(_run_ndvi_sync, source_path, output_dir, args, settings)
    return stats, {"mode": "local_subprocess", "fallback_used": False, "error_code": None}


async def _handle_docker_failure(
    exc: Exception,
    code: str,
    source_path: Path,
    output_dir: Path,
    args: NDVIArguments,
    settings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not settings.ndvi_mcp_allow_local_fallback:
        raise NDVIExecutionError(f"Docker MCP 执行失败且本地回退已禁用: {exc}", code) from exc

    logger.warning("[NDVI] Docker MCP failed (%s); falling back to local subprocess.", exc)
    stats = await asyncio.to_thread(_run_ndvi_sync, source_path, output_dir, args, settings)
    return stats, {"mode": "local_fallback", "fallback_used": True, "error_code": code}


async def _run_docker(source_path: Path, output_dir: Path, args: NDVIArguments, settings) -> dict[str, Any]:
    """Compatibility wrapper for existing tests and callers."""
    stats, _execution = await _run_ndvi_execution(source_path, output_dir, args, settings)
    return stats

import asyncio
import json
import logging
from pathlib import Path
from time import perf_counter

from app.lib.ai.agents.tools.ndvi.formatter import format_ndvi_context
from app.lib.ai.agents.tools.ndvi.schema import NDVIArguments
from app.lib.ai.agents.types import ToolRunResult
from app.schemas.chat import ChatRequest
from app.shared.settings import get_settings

logger = logging.getLogger(__name__)


def _imagery_root() -> Path:
    settings = get_settings()
    root = Path(settings.imagery_upload_dir)
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[6] / root
    return root


async def run_ndvi(args: NDVIArguments, request: ChatRequest) -> ToolRunResult:
    settings = get_settings()
    imagery_dir = _imagery_root() / args.imagery_id
    source_path = imagery_dir / "source.tif"

    if not source_path.exists():
        return ToolRunResult(
            tool_context=f"影像 {args.imagery_id} 不存在，请先上传影像。",
            error="imagery_not_found",
        )

    output_dir = imagery_dir / "results"
    output_dir.mkdir(parents=True, exist_ok=True)

    start = perf_counter()
    try:
        stats = await _run_docker(source_path, output_dir, args, settings)
    except asyncio.TimeoutError:
        return ToolRunResult(
            tool_context="NDVI计算超时，请稍后重试。",
            error="docker_timeout",
        )
    except NDVIExecutionError as exc:
        return ToolRunResult(
            tool_context=f"NDVI计算失败: {exc}",
            error=str(exc),
        )
    except FileNotFoundError:
        logger.error("Docker command not found. Is Docker installed and in PATH?")
        return ToolRunResult(
            tool_context="NDVI计算失败: Docker未安装或不在系统PATH中，请确保Docker已安装并启动。",
            error="docker_not_found",
        )
    except Exception as exc:
        logger.exception(f"NDVI unexpected error: {exc}")
        return ToolRunResult(
            tool_context=f"NDVI计算失败: {exc}",
            error=str(exc),
        )

    elapsed_ms = int((perf_counter() - start) * 1000)
    logger.info(f"NDVI completed: imagery={args.imagery_id}, elapsed={elapsed_ms}ms")

    result_filename = "ndvi_colored.png"
    tool_context = format_ndvi_context(args.imagery_id, stats, result_filename)

    meta_path = imagery_dir / "metadata.json"
    bounds = None
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        bounds = meta.get("bounds")

    geospatial_result = {
        "type": "ndvi",
        "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{result_filename}",
        "bounds": bounds,
        "stats": stats,
    }

    return ToolRunResult(
        tool_context=tool_context,
        result_count=1,
        query=f"NDVI({args.imagery_id})",
        geospatial_result=geospatial_result,
    )


class NDVIExecutionError(Exception):
    pass


async def _run_docker(source_path: Path, output_dir: Path, args: NDVIArguments, settings) -> dict:
    source_abs = str(source_path.resolve()).replace("\\", "/")
    output_abs = str(output_dir.resolve()).replace("\\", "/")

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{source_abs}:/data/input.tif:ro",
        "-v", f"{output_abs}:/data/output",
        "-e", f"RED_BAND={args.red_band}",
        "-e", f"NIR_BAND={args.nir_band}",
    ]
    if settings.ndvi_docker_gpu:
        cmd.extend(["--gpus", "all"])
    cmd.append(settings.ndvi_docker_image)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(),
        timeout=settings.ndvi_docker_timeout_seconds,
    )

    if proc.returncode != 0:
        error_msg = stderr.decode(errors="replace").strip()[:500]
        raise NDVIExecutionError(error_msg or f"exit code {proc.returncode}")

    stats_path = output_dir / "stats.json"
    if not stats_path.exists():
        raise NDVIExecutionError("容器未生成 stats.json")

    return json.loads(stats_path.read_text(encoding="utf-8"))

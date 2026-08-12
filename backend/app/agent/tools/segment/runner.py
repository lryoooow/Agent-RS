from __future__ import annotations

import asyncio
import logging
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.agent.tools.common import (
    IMAGERY_ID_PATTERN,
    execution_metadata,
    imagery_not_found_result,
    invalid_bands_result,
    invalid_imagery_id_result,
    read_bounds,
    resolve_imagery_paths,
    validate_band_indices,
)
from app.agent.tools.segment.formatter import format_segment_context
from app.agent.tools.segment.schema import SegmentArguments
from app.agent.types import AgentArtifact, ToolRunResult
from app.core.settings import get_settings
from app.mcp.client import MCPCallError
from app.mcp.rs_tools_client import RSToolsMCPClient
from app.schemas.chat import ToolExecutionInfo

logger = logging.getLogger(__name__)


class ROISelectionError(ValueError):
    pass


@dataclass(frozen=True)
class _ROICrop:
    path: Path
    bounds_wgs84: tuple[float, float, float, float] | None


async def run_segment(args: SegmentArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("地物分割")
    source_path, imagery_dir, results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)
    results_dir.mkdir(parents=True, exist_ok=True)

    band_error = await validate_band_indices(
        source_path,
        {"red": args.red_band, "green": args.green_band, "blue": args.blue_band},
    )
    if band_error:
        return invalid_bands_result("地物分割", band_error)

    settings = get_settings()
    if not settings.rs_segment_mcp_use_docker:
        return _error_result("地物分割失败: RS Tools Docker MCP 未启用。", "mcp_disabled")
    payload = {
        "red_band": args.red_band,
        "green_band": args.green_band,
        "blue_band": args.blue_band,
    }
    crop: _ROICrop | None = None
    job_dir: Path | None = None
    try:
        if args.bbox is not None or args.pixel_bbox is not None:
            crop = await asyncio.to_thread(
                _crop_to_roi,
                source_path,
                imagery_dir,
                bbox=args.bbox,
                bbox_crs=args.bbox_crs,
                pixel_bbox=args.pixel_bbox,
            )
            source_path = crop.path
            # The Docker tool has a fixed output filename.  Isolate every ROI job,
            # then promote its PNG to a unique flat result name to avoid races and
            # stale browser caches across successive selections.
            job_dir = results_dir / f".segment_roi_{uuid4().hex}"
            job_dir.mkdir(parents=True, exist_ok=False)
        result = await _client(settings).call_tool(
            "segment_landcover",
            source_path=source_path,
            output_dir=job_dir or results_dir,
            arguments=payload,
        )
        result_filename = Path(
            str(result.get("output_png") or "segmentation_overlay.png")
        ).name
        if job_dir is not None:
            generated = job_dir / result_filename
            if not generated.is_file():
                raise MCPCallError("ROI segmentation did not produce its output image")
            unique_filename = f"segmentation_roi_{uuid4().hex[:16]}.png"
            generated.replace(results_dir / unique_filename)
            result_filename = unique_filename
    except ROISelectionError as exc:
        logger.info("Land-cover ROI rejected: %s", exc)
        return _error_result(f"地物分类选区无效：{exc}", "invalid_roi")
    except (FileNotFoundError, asyncio.TimeoutError, MCPCallError) as exc:
        logger.warning("Land-cover segmentation failed: %s", exc)
        return _error_result("地物分割失败，请稍后重试或检查影像与服务状态。", "mcp_error")
    except Exception as exc:
        logger.exception("Land-cover segmentation unexpected error: %s", exc)
        return _error_result("地物分割失败，请稍后重试或检查影像与服务状态。", "unexpected_error")
    finally:
        if crop is not None:
            crop.path.unlink(missing_ok=True)
        if job_dir is not None:
            shutil.rmtree(job_dir, ignore_errors=True)

    execution_info = ToolExecutionInfo(mode="docker_mcp", fallback_used=False)
    geospatial_result = {
        "type": "segmentation",
        "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{result_filename}",
        "bounds": crop.bounds_wgs84 if crop is not None else read_bounds(imagery_dir / "metadata.json"),
        "total_pixels": int(result.get("total_pixels", 0)),
        "classes": result.get("classes") or [],
        "execution": execution_info.model_dump(exclude_none=True),
    }
    return ToolRunResult(
        tool_context=format_segment_context(args.imagery_id, result, result_filename),
        result_count=len(result.get("classes") or []),
        query=f"segment_landcover({args.imagery_id})",
        geospatial_result=geospatial_result,
        artifacts=[AgentArtifact(type="geospatial", payload=geospatial_result)],
        metadata=execution_metadata("docker_mcp"),
    )


def _crop_to_roi(
    source_path: Path,
    imagery_dir: Path,
    *,
    bbox: tuple[float, float, float, float] | None,
    bbox_crs: str | None,
    pixel_bbox: tuple[float, float, float, float] | None,
) -> _ROICrop:
    import rasterio
    from rasterio.crs import CRS
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, bounds as window_bounds, from_bounds

    output_path = imagery_dir / f".segment_roi_{uuid4().hex}.tif"
    try:
        with rasterio.open(source_path) as src:
            if pixel_bbox is not None:
                x0, y0, x1, y1 = pixel_bbox
                col0 = max(0, math.floor(x0 * src.width))
                row0 = max(0, math.floor(y0 * src.height))
                col1 = min(src.width, math.ceil(x1 * src.width))
                row1 = min(src.height, math.ceil(y1 * src.height))
            elif bbox is not None:
                if src.crs is None:
                    raise ROISelectionError("影像没有坐标系，请在影像查看器中使用像素框选。")
                try:
                    requested = transform_bounds(
                        CRS.from_user_input(bbox_crs),
                        src.crs,
                        *bbox,
                        densify_pts=21,
                    )
                except Exception as exc:
                    raise ROISelectionError("无法转换选区坐标系。") from exc
                left = max(requested[0], src.bounds.left)
                bottom = max(requested[1], src.bounds.bottom)
                right = min(requested[2], src.bounds.right)
                top = min(requested[3], src.bounds.top)
                if not (left < right and bottom < top):
                    raise ROISelectionError("框选范围与当前影像不相交。")
                floating = from_bounds(left, bottom, right, top, src.transform)
                col0 = max(0, math.floor(floating.col_off))
                row0 = max(0, math.floor(floating.row_off))
                col1 = min(src.width, math.ceil(floating.col_off + floating.width))
                row1 = min(src.height, math.ceil(floating.row_off + floating.height))
            else:  # pragma: no cover - caller only invokes this helper for a ROI
                raise ROISelectionError("缺少选区参数。")

            if col1 <= col0 or row1 <= row0:
                raise ROISelectionError("选区小于一个有效像素。")
            window = Window(col0, row0, col1 - col0, row1 - row0)
            profile = src.profile.copy()
            profile.update(
                width=int(window.width),
                height=int(window.height),
                transform=src.window_transform(window),
                tiled=False,
            )
            profile.pop("blockxsize", None)
            profile.pop("blockysize", None)
            data = src.read(window=window)
            native_bounds = window_bounds(window, src.transform)
            bounds_wgs84 = (
                tuple(transform_bounds(src.crs, "EPSG:4326", *native_bounds, densify_pts=21))
                if src.crs is not None
                else None
            )
            with rasterio.open(output_path, "w", **profile) as dst:
                dst.write(data)
        return _ROICrop(
            path=output_path,
            bounds_wgs84=bounds_wgs84,  # type: ignore[arg-type]
        )
    except ROISelectionError:
        output_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        output_path.unlink(missing_ok=True)
        raise ROISelectionError("无法从影像裁出该选区。") from exc


def _client(settings) -> RSToolsMCPClient:
    return RSToolsMCPClient(
        image=settings.rs_segment_mcp_image,
        timeout_seconds=settings.rs_segment_docker_timeout_seconds,
        memory_limit=settings.rs_segment_mcp_memory_limit,
        cpus=settings.rs_segment_mcp_cpus,
        network=settings.rs_segment_mcp_network,
        gpus=settings.rs_segment_mcp_gpus or None,
    )


def _error_result(message: str, code: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=message,
        error=code,
        metadata=execution_metadata("failed", error_code=code),
    )

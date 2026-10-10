from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from pathlib import Path
import re
import shutil
from uuid import uuid4

import httpx

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
from app.agent.tools.instance_segment.formatter import format_instance_segment_context
from app.agent.tools.instance_segment.schema import InstanceSegmentArguments
from app.agent.tools.roi_crop import ROISelectionError, crop_to_roi
from app.agent.types import AgentArtifact, ToolRunResult
from app.core.settings import get_settings
from app.core.resource_limits import resource_semaphore
from app.services.imagery_persist import await_settled_operation
from app.mcp.concurrency import tool_semaphore
from app.schemas.chat import ToolExecutionInfo
from app.services.raster_semantics import resolve_rgb

logger = logging.getLogger(__name__)


async def run_instance_segment(args: InstanceSegmentArguments) -> ToolRunResult:
    async with resource_semaphore("raster", get_settings().raster_preprocess_max_concurrent):
        return await _run_instance_segment(args)


async def _run_instance_segment(args: InstanceSegmentArguments) -> ToolRunResult:
    if not IMAGERY_ID_PATTERN.fullmatch(args.imagery_id):
        return invalid_imagery_id_result("SAM3 实例分割")
    source_path, imagery_dir, results_dir = resolve_imagery_paths(args.imagery_id)
    if source_path is None:
        return imagery_not_found_result(args.imagery_id)
    # SAM3 benefits materially from native object scale. Platform working.tif may
    # be a 4096 px analysis proxy; prefer the original grid when it is available.
    native_source = imagery_dir / "source.tif"
    if native_source.is_file():
        source_path = native_source
    results_dir.mkdir(parents=True, exist_ok=True)

    try:
        rgb = await await_settled_operation(asyncio.to_thread(
            resolve_rgb,
            source_path,
            {"red": args.red_band, "green": args.green_band, "blue": args.blue_band},
            explicit={"red_band", "green_band", "blue_band"} & args.model_fields_set,
        ))
    except ValueError as exc:
        return invalid_bands_result("SAM3 RGB 分析", str(exc))
    args = args.model_copy(update={name + "_band": index for name, index in rgb.items()})
    band_error = await validate_band_indices(
        source_path,
        {"red": args.red_band, "green": args.green_band, "blue": args.blue_band},
    )
    if band_error:
        return invalid_bands_result("SAM3 实例分割", band_error)

    settings = get_settings()
    if not settings.sam3_enabled:
        return _error_result("SAM3 服务未启用，本次没有运行推理。", "service_disabled")

    crop = None
    inference_source = source_path
    job_dir = results_dir / f".sam3_{uuid4().hex}"
    display_bounds = None
    inference_started = False
    inference_settled = False
    try:
        if args.bbox is not None or args.pixel_bbox is not None:
            async def make_crop():
                nonlocal crop
                crop = await asyncio.to_thread(crop_to_roi, source_path, imagery_dir,
                    bbox=args.bbox, bbox_crs=args.bbox_crs, pixel_bbox=args.pixel_bbox)
            await await_settled_operation(make_crop())
            inference_source = crop.path
            display_bounds = crop.bounds_wgs84
        job_dir.mkdir(parents=True, exist_ok=False)
        input_png = job_dir / "input.png"
        png_grid = await await_settled_operation(asyncio.to_thread(
            _write_rgb_png,
            inference_source,
            input_png,
            args.red_band,
            args.green_band,
            args.blue_band,
        ))
        timeout = httpx.Timeout(
            settings.sam3_inference_timeout_seconds,
            connect=min(10.0, settings.sam3_inference_timeout_seconds),
        )
        async def infer_and_settle():
            nonlocal inference_started, inference_settled
            async with tool_semaphore():
                async with httpx.AsyncClient(timeout=timeout) as client:
                    inference_started = True
                    response = await client.post(f"{settings.sam3_service_url.rstrip('/')}/infer",
                        json={"input_path":str(input_png.resolve()),"output_dir":str(job_dir.resolve()),"concepts":args.concepts})
                    inference_settled = response.is_success or response.headers.get("X-SAM3-Settled")=="1"
                    response.raise_for_status()
                    return response.json()
        result = await await_settled_operation(infer_and_settle())
        promoted = await await_settled_operation(asyncio.to_thread(_promote_outputs,
            job_dir, results_dir, inference_source, result, inference_grid=png_grid))
    except ROISelectionError as exc:
        return _error_result(f"SAM3 选区无效：{exc}", "invalid_roi")
    except httpx.ConnectError:
        logger.warning("SAM3 service is unavailable", exc_info=True)
        return _error_result("SAM3 推理服务不可用，本次没有产生结果；需要检查本地 GPU 服务。", "service_unavailable")
    except httpx.TimeoutException:
        logger.warning("SAM3 inference timed out", exc_info=True)
        return _error_result("SAM3 推理超时，未取得完整结果；可缩小框选区域后再执行。", "inference_timeout")
    except httpx.HTTPStatusError as exc:
        logger.warning("SAM3 service returned HTTP %s", exc.response.status_code)
        return _error_result("SAM3 推理服务返回错误，未产出可用结果；详细原因已写入服务日志。", "service_error")
    except Exception:
        logger.exception("SAM3 instance segmentation failed")
        return _error_result("SAM3 实例分割发生异常，未产出可用结果。", "unexpected_error")
    finally:
        if inference_started and not inference_settled:
            # A network timeout cannot prove that the GPU stopped reading input.
            try:
                job_dir.mkdir(parents=True, exist_ok=True)
                (job_dir / "outcome_unknown.json").write_text(json.dumps({"imagery_id":args.imagery_id,
                    "state":"outcome_unknown","crop_path":str(crop.path) if crop else None}),encoding="utf-8")
            except OSError:
                logger.warning("Unable to record unsettled SAM3 job; private files retained")
            logger.warning("SAM3 completion unknown; retaining private input: %s", job_dir.name)
        else:
            if crop is not None:
                crop.path.unlink(missing_ok=True)
            shutil.rmtree(job_dir, ignore_errors=True)

    bounds = display_bounds or read_bounds(imagery_dir / "metadata.json")
    execution = ToolExecutionInfo(mode="local_service", fallback_used=False)
    geospatial_result = {
        "type": "instance_segmentation",
        "imagery_id": args.imagery_id,
        "result_url": f"/api/imagery/{args.imagery_id}/results/{promoted['overlay']}",
        "bounds": bounds,
        "model_name": "SAM3",
        "inference_grid": {"width":png_grid[0],"height":png_grid[1]},
        "resampled": promoted.get("resampled", False),
        "device": result.get("device") or "hygon-dcu",
        "concepts": args.concepts,
        "instance_count": int(result.get("instance_count") or 0),
        "counts": result.get("counts") or {},
        "union_pixels": int(result.get("union_pixels") or 0),
        "area_m2": promoted.get("area_m2"),
        "mask_url": f"/api/imagery/{args.imagery_id}/results/{promoted['mask_tif']}",
        "instance_raster_url": f"/api/imagery/{args.imagery_id}/results/{promoted['labels_tif']}",
        "vector_url": (
            f"/api/imagery/{args.imagery_id}/results/{promoted['geojson']}"
            if promoted.get("geojson") else None
        ),
        "instances_url": f"/api/imagery/{args.imagery_id}/results/{promoted['instances']}",
        "metrics_url": f"/api/imagery/{args.imagery_id}/results/{promoted['metrics']}",
        "execution": execution.model_dump(exclude_none=True),
    }
    context_result = {**result, "area_m2": promoted.get("area_m2"), "inference_grid":png_grid,
        "resampled":promoted.get("resampled",False)}
    return ToolRunResult(
        tool_context=format_instance_segment_context(args.imagery_id, context_result),
        result_count=int(result.get("instance_count") or 0),
        query=f"segment_instances({args.imagery_id}, {','.join(args.concepts)})",
        geospatial_result=geospatial_result,
        artifacts=[AgentArtifact(type="geospatial", payload=geospatial_result)],
        metadata=execution_metadata("local_service"),
    )


def _write_rgb_png(
    source_path: Path,
    output_path: Path,
    red_band: int,
    green_band: int,
    blue_band: int,
) -> tuple[int, int]:
    """导出推理用 RGB PNG（G3：读取前按 sam3_max_pixels 预算限制像元数）。

    历史缺陷：无条件 masked=True 整幅读取——9000x9000（81M 像素 > 服务端 64M
    上限）的 730KB 源即可迫使后端主进程分配 ~1.4GB，且产出的 PNG 注定被
    ops/sam3_service.py 的 MAX_PIXELS 检查拒绝（先读入再被服务拒绝）。
    修复：读取前检查 width×height，超过 settings.sam3_max_pixels（与服务端
    SAM3_MAX_PIXELS 同名同默认）时按 sqrt 比例降采样（out_shape + bilinear）。

    返回实际写入的 PNG 网格 (width, height)——降采样时与源网格不同，
    _promote_outputs 据此对齐输出栅格的尺寸与 transform。
    """
    import numpy as np
    from PIL import Image
    import rasterio
    from rasterio.enums import Resampling

    settings = get_settings()
    with rasterio.Env(GDAL_CACHEMAX=32*1024*1024), rasterio.open(source_path) as src:
        max_pixels = min(settings.sam3_max_pixels, (settings.sam3_preprocess_max_bytes - 32*1024*1024) // 64)
        if src.width * src.height > max_pixels:
            # 按面积比例的线性缩放：两维同乘 sqrt(上限/实际)，保持宽高比。
            scale = (max_pixels / (src.width * src.height)) ** 0.5
            out_width = max(1, int(src.width * scale))
            out_height = max(1, int(src.height * scale))
            # Clamping a thin raster's short edge to one can exceed the budget.
            if out_width * out_height > max_pixels:
                if out_width >= out_height:
                    out_width = max(1, max_pixels // out_height)
                else:
                    out_height = max(1, max_pixels // out_width)
            data = src.read(
                [red_band, green_band, blue_band],
                masked=True,
                out_shape=(3, out_height, out_width),
                resampling=Resampling.bilinear,
            )
        else:
            out_width, out_height = src.width, src.height
            data = src.read([red_band, green_band, blue_band], masked=True)
    output = np.zeros((data.shape[1], data.shape[2], 3), dtype=np.uint8)
    for index in range(3):
        band = data[index]
        values = band.compressed()
        if not values.size:
            continue
        if band.dtype == np.uint8:
            scaled = band.filled(0).astype(np.uint8)
        else:
            sample = values[::max(1, math.ceil(values.size / 262144))].astype(np.float32)
            sample = sample[np.isfinite(sample)]
            if not sample.size:
                continue
            low, high = np.percentile(sample, [2, 98])
            if not math.isfinite(float(low)) or not math.isfinite(float(high)) or high <= low:
                scaled = np.zeros(band.shape, dtype=np.uint8)
            else:
                scaled = np.clip((band.filled(low).astype(np.float32) - low) * 255.0 / (high - low), 0, 255).astype(np.uint8)
        output[:, :, index] = scaled
    Image.fromarray(output, mode="RGB").save(output_path)
    return out_width, out_height


def _promote_outputs(
    job_dir: Path,
    results_dir: Path,
    source_path: Path,
    result: dict,
    *,
    inference_grid: tuple[int, int] | None = None,
) -> dict:
    """把 SAM3 服务端产物落成平台结果文件。

    inference_grid：实际推理网格 (width, height)（_write_rgb_png 的返回值）。
    与源网格不同（G3 降采样发生）时，mask/labels GeoTIFF 按推理网格尺寸写出、
    transform 按缩放比例校正、像元面积按缩放比例放大——保证 geojson 与栅格
    坐标一致；与源网格相同时所有行为与降采样支持之前逐行一致。
    """
    import numpy as np
    from PIL import Image
    import rasterio
    from rasterio.features import shapes
    from rasterio.warp import transform_geom

    suffix = uuid4().hex[:16]
    slug = re.sub(r"[^a-z0-9]+", "_", "_".join(result.get("counts", {}).keys()).lower()).strip("_")[:36] or "objects"
    overlay_name = f"sam3_{slug}_{suffix}.png"
    mask_name = f"sam3_{slug}_mask_{suffix}.tif"
    labels_name = f"sam3_{slug}_instances_{suffix}.tif"
    geojson_name = f"sam3_{slug}_{suffix}.geojson"
    instances_name = f"sam3_{slug}_{suffix}.json"
    metrics_name = f"sam3_{slug}_metrics_{suffix}.json"

    overlay_path = job_dir / overlay_name
    instances_path = job_dir / instances_name
    metrics_path = job_dir / metrics_name
    mask_path = job_dir / mask_name
    labels_path = job_dir / labels_name
    geojson_path = job_dir / geojson_name

    for key in ("overlay_png", "instances_json", "metrics_json", "union_png", "labels_npy"):
        name=str(result[key])
        candidate=job_dir/name
        if Path(name).name != name or candidate.is_symlink() or not candidate.is_file():
            raise ValueError("invalid SAM3 output path")
    (job_dir / str(result["overlay_png"])).replace(overlay_path)
    (job_dir / str(result["instances_json"])).replace(instances_path)
    (job_dir / str(result["metrics_json"])).replace(metrics_path)
    union = np.asarray(Image.open(job_dir / str(result["union_png"])).convert("L")) > 0
    labels = np.load(job_dir / str(result["labels_npy"]), allow_pickle=False, mmap_mode="r")
    records = json.loads(instances_path.read_text(encoding="utf-8"))
    record_by_label = {int(item["label_id"]): item for item in records}

    with rasterio.open(source_path) as src:
        grid = inference_grid or (src.width, src.height)
        grid_width, grid_height = grid
        if union.shape != (grid_height, grid_width) or labels.shape != (grid_height, grid_width):
            raise ValueError("SAM3 output grid does not match inference source")
        base_profile = src.profile.copy()
        transform = src.transform
        crs = src.crs
        if grid != (src.width, src.height):
            # 降采样推理（G3）：推理网格 -> 源坐标的仿射缩放，与工作图同款算法。
            transform = src.transform * src.transform.scale(
                src.width / grid_width, src.height / grid_height
            )
        mask_profile = {
            **base_profile,
            "driver": "GTiff",
            "height": grid_height,
            "width": grid_width,
            "transform": transform,
            "count": 1,
            "dtype": "uint8",
            "nodata": 0,
            "compress": "deflate",
        }
        with rasterio.open(mask_path, "w", **mask_profile) as dst:
            dst.write(union.astype(np.uint8), 1)
        labels_profile = {**mask_profile, "dtype": "uint32", "nodata": 0}
        with rasterio.open(labels_path, "w", **labels_profile) as dst:
            dst.write(labels.astype(np.uint32), 1)
        pixel_area = _pixel_area_m2(src)
        if pixel_area is not None and grid != (src.width, src.height):
            # 推理像元 = 缩放后的粗像元，面积为源像元面积 × 两维缩放系数之积。
            pixel_area = pixel_area * (src.width / grid_width) * (src.height / grid_height)

    features: list[dict] = []
    if crs is not None and labels.any():
        for geometry, label_value in shapes(labels.astype(np.int32), mask=labels > 0, transform=transform):
            label_id = int(label_value)
            record = record_by_label.get(label_id, {})
            try:
                geometry_wgs84 = transform_geom(crs, "EPSG:4326", geometry, precision=7)
            except Exception:
                continue
            features.append({
                "type": "Feature",
                "geometry": geometry_wgs84,
                "properties": {
                    "label_id": label_id,
                    "instance_id": record.get("id"),
                    "concept": record.get("concept"),
                    "score": record.get("score"),
                    "mask_pixels": record.get("mask_pixels"),
                    "area_m2": (float(record.get("mask_pixels", 0)) * pixel_area if pixel_area is not None else None),
                },
            })
        geojson_path.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
            encoding="utf-8",
        )

    completed = [overlay_path, mask_path, labels_path, instances_path, metrics_path]
    if features:
        completed.append(geojson_path)
    promoted: list[Path] = []
    try:
        for path in completed:
            destination = results_dir / path.name
            os.link(path, destination)
            promoted.append(destination)
            path.unlink()
    except Exception:
        for path in promoted:
            path.unlink(missing_ok=True)
        raise

    return {
        "overlay": overlay_name,
        "mask_tif": mask_name,
        "labels_tif": labels_name,
        "geojson": geojson_name if features else None,
        "instances": instances_name,
        "metrics": metrics_name,
        "area_m2": float(union.sum()) * pixel_area if pixel_area is not None else None,
        "resampled": grid != (src.width, src.height),
    }


def _pixel_area_m2(dataset) -> float | None:
    from rasterio.warp import transform

    if dataset.crs is None:
        return None
    determinant = abs(dataset.transform.a * dataset.transform.e - dataset.transform.b * dataset.transform.d)
    if dataset.crs.is_projected:
        try:
            unit = dataset.crs.linear_units_factor
            factor = float(unit[1] if isinstance(unit, tuple) else unit)
            if factor > 0:
                return determinant * factor * factor
        except Exception:
            pass
    row = dataset.height // 2
    col = dataset.width // 2
    corners = [dataset.transform * (col, row), dataset.transform * (col + 1, row), dataset.transform * (col + 1, row + 1), dataset.transform * (col, row + 1)]
    lon, lat = transform(dataset.crs, "EPSG:4326", [p[0] for p in corners], [p[1] for p in corners])
    radius = 6_371_008.8
    latitude0 = math.radians(sum(lat) / len(lat))
    points = [(radius * math.radians(x) * math.cos(latitude0), radius * math.radians(y)) for x, y in zip(lon, lat)]
    area = abs(sum(points[i][0] * points[(i + 1) % 4][1] - points[(i + 1) % 4][0] * points[i][1] for i in range(4))) / 2
    return area if math.isfinite(area) and area > 0 else None


def _error_result(message: str, code: str) -> ToolRunResult:
    return ToolRunResult(
        tool_context=message,
        error=code,
        metadata=execution_metadata("failed", error_code=code),
    )

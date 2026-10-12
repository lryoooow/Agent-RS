"""Loopback-only SAM3 image inference service for the Hygon DCU host.

The systemd unit supplies the validated SAM3 lab paths and Hygon runtime library
environment. Agent-RS sends only RGB PNGs created from imagery the current user
already owns; this process never reads arbitrary client paths.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

LAB_ROOT = Path(os.environ.get("SAM3_LAB_ROOT", "/home/LRY/sam3-runtime-releases/20260922-meta-2345a4ad")).resolve()
for entry in (LAB_ROOT / "source",):
    sys.path.insert(0, str(entry))

import numpy as np
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field, field_validator
from PIL import Image

from ops.sam3_runtime.geometry import deduplicate, make_instance, tiles, union_mask
from ops.sam3_runtime.runtime import Engine

ALLOWED_ROOT = Path(
    os.environ.get("SAM3_ALLOWED_ROOT", "/home/LRY/Agent-RS/storage/imagery")
).resolve()
MAX_PIXELS = int(os.environ.get("SAM3_MAX_PIXELS", str(64 * 1024 * 1024)))
TILE_SIZE = int(os.environ.get("SAM3_TILE_SIZE", "1024"))
TILE_OVERLAP = int(os.environ.get("SAM3_TILE_OVERLAP", "256"))

CONFIDENCE_THRESHOLD = float(os.environ.get("SAM3_CONFIDENCE_THRESHOLD", "0.25"))
# 最小实例面积（推理网格像元）：跨切片合并完成后，低于该值的连通掩膜按碎片噪声
# 丢弃，不进入实例计数与面积统计。默认 32 像元的依据：推理切片为 TILE_SIZE=1024
# 的方形网格，32 像元约占单切片面积的 0.003%，且小于 6x6 像元的掩膜多边形化后
# 只剩若干个格点、给不出可用的边界轮廓；本能力定位的最小目标类别（建筑/船舶/
# 车辆，docs/segmentation-deployment.md）在亚米级影像上通常达数十像元以上。
# 该阈值与 geometry.deduplicate 的跨切片碎片合并判据互补：后者只合并来自不同
# 切片的视角对，不处理孤立噪声碎块。设为 0 可关闭过滤。
MIN_INSTANCE_AREA = int(os.environ.get("SAM3_MIN_INSTANCE_AREA", "32"))
SOURCE_COMMIT = "2345a4ad109ac29c569da749c91d84f10dc08c40"
SOURCE_SHA256 = "26a4f92919756ad412e111b20868f4bc1f2b2d7170214ab5cdae1669d6051f1a"
CHECKPOINT_SHA256 = "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e"
if not 0.0 <= CONFIDENCE_THRESHOLD <= 1.0:
    raise RuntimeError("SAM3 confidence threshold must be within [0, 1]")
if TILE_SIZE < 64 or not 0 <= TILE_OVERLAP < TILE_SIZE or MAX_PIXELS < 1:
    raise RuntimeError("Invalid SAM3 image or tile limits")
if MIN_INSTANCE_AREA < 0:
    raise RuntimeError("SAM3 minimum instance area must be non-negative")


class InferRequest(BaseModel):
    input_path: str
    output_dir: str
    concepts: list[str] = Field(min_length=1, max_length=6)

    @field_validator("concepts")
    @classmethod
    def validate_concepts(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            concept = " ".join(value.strip().lower().split())
            if not concept or len(concept) > 60 or any(c in concept for c in "/\\\x00\n\r"):
                raise ValueError("invalid concept")
            if concept not in result:
                result.append(concept)
        return result


app = FastAPI(title="Agent-RS SAM3 service", docs_url=None, redoc_url=None)
engine: Engine | None = None
loaded_at: float | None = None
_inference_lock = asyncio.Lock()


def _allowed(path_value: str, *, directory: bool = False) -> Path:
    path = Path(path_value).resolve()
    if not path.is_relative_to(ALLOWED_ROOT):
        raise HTTPException(status_code=403, detail="path outside imagery storage")
    if directory:
        path.mkdir(parents=True, exist_ok=True)
    elif not path.is_file():
        raise HTTPException(status_code=404, detail="input image not found")
    return path


@app.on_event("startup")
async def load_model() -> None:
    global engine, loaded_at
    engine = await asyncio.to_thread(Engine, CONFIDENCE_THRESHOLD)
    loaded_at = time.time()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok" if engine is not None else "loading",
        "model": "SAM3",
        "device": "hygon-dcu",
        "provider": "meta_official_sam3",
        "source_commit": SOURCE_COMMIT,
        "source_sha256": SOURCE_SHA256,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "tile_size": TILE_SIZE,
        "tile_overlap": TILE_OVERLAP,
        "min_instance_area": MIN_INSTANCE_AREA,
        "loaded_at": loaded_at,
    }


def _effective_tile_mask(
    mask: np.ndarray,
    valid: np.ndarray,
    extent: tuple[int, int, int, int],
) -> np.ndarray:
    """有效区掩膜（S1/S2 共用同一实现）：模型输出的切片掩膜只保留有效像元。

    - S1（PNG Alpha）：valid 来自输入 PNG 的 Alpha 通道（透明=无效），
      透明像元不参与分割、不计入面积统计。
    - S2（边缘切片方形补齐）：非方形切片只在其右侧/下侧补齐到方形，模型
      掩膜经本函数裁回 (y1-y0, x1-x0) 的切片原尺寸，补齐区随之等价于无效。
      两种无效来源共用本实现，任一侧的规则变化另一侧自动一致。
    """
    x0, y0, x1, y1 = extent
    cropped = np.asarray(mask, dtype=bool)[: y1 - y0, : x1 - x0]
    return np.logical_and(cropped, valid[y0:y1, x0:x1])


def _infer(request: InferRequest, input_path: Path, output_dir: Path) -> dict[str, Any]:
    assert engine is not None
    with Image.open(input_path) as source:
        if source.width * source.height > MAX_PIXELS:
            raise ValueError(f"input exceeds {MAX_PIXELS} pixels")
        # PNG Alpha 有效区掩膜（S1）：透明像元不参与分割、不计入面积统计；
        # 无 Alpha 的输入经 convert("RGBA") 补全为全不透明（全有效），行为与旧版一致。
        rgba = source.convert("RGBA")
    valid = np.asarray(rgba)[..., 3] > 0
    image = rgba.convert("RGB")

    started = time.perf_counter()
    extents = tiles(*image.size, TILE_SIZE, TILE_OVERLAP) if max(image.size) > TILE_SIZE else [(0, 0, *image.size)]
    candidates = []
    step_summaries: list[dict[str, Any]] = []
    for tile_id, extent in enumerate(extents):
        x0, y0, x1, y1 = extent
        if not valid[y0:y1, x0:x1].any():
            # 全无效切片：直接跳过，不占用 GPU 推理，只在过程记录中留痕。
            step_summaries.append({
                "tile": tile_id,
                "extent": list(extent),
                "skipped_invalid": True,
                "valid_pixels": 0,
                "embedding_seconds": 0.0,
                "counts": {},
            })
            continue
        tile = image.crop(extent)
        # 边缘切片方形补齐（S2）：短于 TILE_SIZE 的维度产生非方形切片，模型内部
        # 按固定方形网格 resize 会把非方形输入拉伸变形；统一在右侧/下侧补齐到
        # 方形再推理，模型掩膜由 _effective_tile_mask 裁回切片原尺寸——补齐区与
        # S1 的透明区共用同一个有效区掩膜实现，均视为无效。
        side = max(x1 - x0, y1 - y0)
        if tile.width != side or tile.height != side:
            square = Image.new("RGB", (side, side))
            square.paste(tile, (0, 0))
            tile = square
        predictions, embedding_seconds = engine.infer(tile, request.concepts)
        counts: dict[str, int] = {}
        for concept, output in predictions.items():
            counts[concept] = int(len(output["scores"]))
            for index, (mask, score) in enumerate(zip(output["masks"], output["scores"])):
                instance = make_instance(
                    _effective_tile_mask(mask, valid, extent),
                    extent,
                    image.size,
                    f"{concept}-{tile_id}-{index}",
                    concept,
                    float(score),
                    tile_id,
                )
                if instance is not None:
                    candidates.append(instance)
        step_summaries.append({
            "tile": tile_id,
            "extent": list(extent),
            "embedding_seconds": embedding_seconds,
            "valid_pixels": int(valid[y0:y1, x0:x1].sum()),
            "counts": counts,
        })

    instances, suppression_audit = deduplicate(candidates)
    # 微小碎片过滤（S3）：在跨切片合并之后执行——同一大目标的切片碎片先合并、
    # 再按面积判噪声，避免把大目标的合法局部当碎片丢弃。
    retained = [item for item in instances if item.area >= MIN_INSTANCE_AREA]
    dropped_fragments = len(instances) - len(retained)
    instances = retained
    instances.sort(key=lambda item: (request.concepts.index(item.concept), -item.score, item.ident))
    label_map = np.zeros((image.height, image.width), dtype=np.uint32)
    union = union_mask(instances, image.size)
    rgb = np.asarray(image, dtype=np.float32).copy()
    rng = np.random.default_rng(20260916)
    colors = rng.integers(55, 245, (len(instances), 3), dtype=np.uint8)
    records: list[dict[str, Any]] = []
    for label_id, (instance, color) in enumerate(zip(instances, colors), start=1):
        x0, y0, x1, y1 = instance.box
        region = rgb[y0:y1, x0:x1]
        region[instance.mask] = region[instance.mask] * 0.52 + color * 0.48
        target = label_map[y0:y1, x0:x1]
        target[np.logical_and(instance.mask, target == 0)] = label_id
        records.append({
            "label_id": label_id,
            "id": instance.ident,
            "concept": instance.concept,
            "score": instance.score,
            "bbox_xyxy": list(instance.box),
            "mask_pixels": instance.area,
            "touches_internal_tile_edge": instance.truncated,
            "source_tiles": list(instance.source_tiles),
        })

    overlay_name = "sam3_overlay.png"
    union_name = "sam3_union.png"
    labels_name = "sam3_labels.npy"
    instances_name = "sam3_instances.json"
    metrics_name = "sam3_metrics.json"
    Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)).save(output_dir / overlay_name)
    Image.fromarray(union.astype(np.uint8) * 255).save(output_dir / union_name)
    np.save(output_dir / labels_name, label_map, allow_pickle=False)
    (output_dir / instances_name).write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    metrics = {
        "model": "SAM3",
        "provider": "meta_official_sam3",
        "source_commit": SOURCE_COMMIT,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "min_instance_area": MIN_INSTANCE_AREA,
        "dropped_fragments": dropped_fragments,
        "device": "hygon-dcu",
        "input_size": list(image.size),
        "tile_size": TILE_SIZE,
        "tile_overlap": TILE_OVERLAP,
        "tile_count": len(extents),
        "raw_instances": len(candidates),
        "instance_count": len(instances),
        "suppressed_duplicates": len(suppression_audit),
        "counts": {concept: sum(item.concept == concept for item in instances) for concept in request.concepts},
        "union_pixels": int(union.sum()),
        "compute_seconds": time.perf_counter() - started,
        "steps": step_summaries,
        "suppression_audit": suppression_audit,
    }
    (output_dir / metrics_name).write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        **metrics,
        "overlay_png": overlay_name,
        "union_png": union_name,
        "labels_npy": labels_name,
        "instances_json": instances_name,
        "metrics_json": metrics_name,
    }


@app.post("/infer")
async def infer(request: InferRequest, response: Response) -> dict[str, Any]:
    if engine is None:
        raise HTTPException(status_code=503, detail="model is still loading")
    input_path = _allowed(request.input_path)
    output_dir = _allowed(request.output_dir, directory=True)
    if output_dir != input_path.parent:
        raise HTTPException(status_code=400, detail="output directory must be the input job directory")
    async with _inference_lock:
        task=asyncio.create_task(asyncio.to_thread(_infer, request, input_path, output_dir))
        try:
            result=await asyncio.shield(task)
            response.headers["X-SAM3-Settled"]="1"
            return result
        except asyncio.CancelledError:
            # Keep the GPU slot until the actual native worker finishes.
            while not task.done():
                try: await asyncio.shield(task)
                except asyncio.CancelledError: continue
                except Exception: break
            raise
        except Exception as exc:
            raise HTTPException(status_code=500,detail=f"SAM3 inference failed: {type(exc).__name__}",
                headers={"X-SAM3-Settled":"1"}) from exc

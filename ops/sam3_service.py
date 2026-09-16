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

LAB_ROOT = Path(os.environ.get("SAM3_LAB_ROOT", "/home/LRY/sam3-lab-20260916")).resolve()
for entry in (LAB_ROOT, LAB_ROOT / "source", LAB_ROOT / "phase2"):
    sys.path.insert(0, str(entry))

import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator
from PIL import Image

from geometry import deduplicate, make_instance, tiles, union_mask
from runtime import Engine

ALLOWED_ROOT = Path(
    os.environ.get("SAM3_ALLOWED_ROOT", "/home/LRY/Agent-RS/storage/imagery")
).resolve()
MAX_PIXELS = int(os.environ.get("SAM3_MAX_PIXELS", str(64 * 1024 * 1024)))
TILE_SIZE = int(os.environ.get("SAM3_TILE_SIZE", "1024"))
TILE_OVERLAP = int(os.environ.get("SAM3_TILE_OVERLAP", "160"))


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
    engine = await asyncio.to_thread(Engine, 0.5)
    loaded_at = time.time()


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok" if engine is not None else "loading",
        "model": "SAM3",
        "device": "hygon-dcu",
        "loaded_at": loaded_at,
    }


def _infer(request: InferRequest, input_path: Path, output_dir: Path) -> dict[str, Any]:
    assert engine is not None
    image = Image.open(input_path).convert("RGB")
    if image.width * image.height > MAX_PIXELS:
        raise ValueError(f"input exceeds {MAX_PIXELS} pixels")

    started = time.perf_counter()
    extents = tiles(*image.size, TILE_SIZE, TILE_OVERLAP) if max(image.size) > TILE_SIZE else [(0, 0, *image.size)]
    candidates = []
    step_summaries: list[dict[str, Any]] = []
    for tile_id, extent in enumerate(extents):
        x0, y0, x1, y1 = extent
        predictions, embedding_seconds = engine.infer(image.crop(extent), request.concepts)
        counts: dict[str, int] = {}
        for concept, output in predictions.items():
            counts[concept] = int(len(output["scores"]))
            for index, (mask, score) in enumerate(zip(output["masks"], output["scores"])):
                instance = make_instance(
                    mask,
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
            "counts": counts,
        })

    instances, suppression_audit = deduplicate(candidates)
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
async def infer(request: InferRequest) -> dict[str, Any]:
    if engine is None:
        raise HTTPException(status_code=503, detail="model is still loading")
    input_path = _allowed(request.input_path)
    output_dir = _allowed(request.output_dir, directory=True)
    if output_dir != input_path.parent:
        raise HTTPException(status_code=400, detail="output directory must be the input job directory")
    try:
        return await asyncio.to_thread(_infer, request, input_path, output_dir)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"SAM3 inference failed: {type(exc).__name__}: {exc}") from exc

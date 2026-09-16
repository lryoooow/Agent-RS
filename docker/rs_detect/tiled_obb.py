"""Local PyTorch oriented-box inference and overlap deduplication."""
from __future__ import annotations

import os
from pathlib import Path
import numpy as np


def tile_starts(length: int, size: int = 1024, overlap: int = 256) -> list[int]:
    if length <= size:
        return [0]
    starts = list(range(0, length - size + 1, size - overlap))
    if starts[-1] != length - size:
        starts.append(length - size)
    return starts


def merge_rotated(detections: list[dict], iou_threshold: float = 0.45) -> list[dict]:
    from shapely.geometry import Polygon

    kept = []
    by_class: dict[int, list] = {}
    for det in sorted(detections, key=lambda item: item["score"], reverse=True):
        polygon = Polygon(np.asarray(det["polygon"]).reshape(4, 2))
        if not polygon.is_valid or polygon.area <= 0:
            continue
        same_class = by_class.setdefault(det["class_id"], [])
        duplicate = False
        for other in same_class:
            if not polygon.intersects(other):
                continue
            intersection = polygon.intersection(other).area
            if intersection / (polygon.area + other.area - intersection) > iou_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(det)
            same_class.append(polygon)
    return kept


def infer(rgb: np.ndarray, score_threshold: float, class_names: list[str]) -> tuple[list[dict], dict]:
    import torch
    from ultralytics import YOLO

    model_path = Path(os.environ.get("RS_DETECT_MODEL_PATH", "/app/yolo11s-obb.pt"))
    if not model_path.is_file():
        raise RuntimeError("Local detection checkpoint is missing")
    use_gpu = torch.cuda.is_available()
    if os.environ.get("RS_DETECT_REQUIRE_GPU", "0") == "1" and not use_gpu:
        raise RuntimeError("GPU runtime is unavailable; refusing a silent CPU fallback")
    device = 0 if use_gpu else "cpu"
    model = YOLO(str(model_path), task="obb")
    names = [model.names[i].replace(" ", "-") for i in range(len(model.names))]
    if set(names) != set(class_names):
        raise RuntimeError("Checkpoint classes do not match DOTA-15")
    # DOTA implementations use different numeric label orders. Map by name.
    class_ids = {i: class_names.index(name) for i, name in enumerate(names)}
    height, width = rgb.shape[:2]
    detections = []
    tile_count = 0
    with torch.inference_mode():
        for y in tile_starts(height):
            for x in tile_starts(width):
                tile = rgb[y:y+1024, x:x+1024]
                # Ultralytics numpy inputs use OpenCV BGR order.
                result = model.predict(source=tile[..., ::-1].copy(), imgsz=1024,
                    conf=score_threshold, iou=0.45, device=device, half=False,
                    verbose=False, save=False, max_det=1000)[0]
                tile_count += 1
                if result.obb is None:
                    continue
                polygons = result.obb.xyxyxyxy.cpu().numpy()
                ids = result.obb.cls.cpu().numpy().astype(int)
                scores = result.obb.conf.cpu().numpy()
                for points, class_id, score in zip(polygons, ids, scores):
                    class_id = class_ids[int(class_id)]
                    points = points + np.asarray([x, y])
                    detections.append({"class_id": int(class_id), "class_name": class_names[class_id],
                        "score": float(score), "polygon": points.reshape(-1).tolist()})
    return merge_rotated(detections), {"device": torch.cuda.get_device_name(0) if use_gpu else "CPU",
        "tile_count": tile_count, "tile_size": 1024, "overlap": 256, "merge_iou": 0.45}

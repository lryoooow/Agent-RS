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
    padded_tiles = 0
    with torch.inference_mode():
        for y in tile_starts(height):
            for x in tile_starts(width):
                tile = rgb[y:y+1024, x:x+1024]
                tile_h, tile_w = tile.shape[:2]
                # 边缘切片方形补齐：任一维度短于 1024 时切片非方形，直送后 Ultralytics
                # letterbox 会自动重采样（内容被缩放，与内部 1024 原生尺度切片的观测
                # 尺度不一致）并在两侧注入灰条合成内容——模型可能在合成区检出假框，
                # 坐标回映后被裁剪成贴边的真实坐标框。统一在右侧/下侧补黑色（与
                # _read_rgb 中有效区外像元的填色一致）到 1024 方形：推理输入恒为原生
                # 尺度的 1024x1024，letterbox 退化为恒等变换，不再有合成灰条。
                if tile_h < 1024 or tile_w < 1024:
                    square = np.zeros((1024, 1024, 3), dtype=tile.dtype)
                    square[:tile_h, :tile_w] = tile
                    tile = square
                    padded_tiles += 1
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
                    # 补齐区内不得出现检测框：中心落在切片原尺寸之外的检出来自合成
                    # 内容，直接丢弃（与 compute_detect 侧按 dataset_mask 中心过滤
                    # 全图有效区互补：本层拦补齐区，那层拦栅格无效区）。补齐只发生
                    # 在右侧/下侧，保留的检出坐标天然落在切片原坐标系，无需平移。
                    if points[:, 0].mean() >= tile_w or points[:, 1].mean() >= tile_h:
                        continue
                    class_id = class_ids[int(class_id)]
                    points = points + np.asarray([x, y])
                    detections.append({"class_id": int(class_id), "class_name": class_names[class_id],
                        "score": float(score), "polygon": points.reshape(-1).tolist()})
    return merge_rotated(detections), {"device": torch.cuda.get_device_name(0) if use_gpu else "CPU",
        "tile_count": tile_count, "tile_size": 1024, "overlap": 256, "merge_iou": 0.45,
        "edge_tiles_padded": padded_tiles}

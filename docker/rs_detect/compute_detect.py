"""PP-YOLOE-R rotated-box detection over a raster, rendered as a transparent PNG overlay."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

# DOTA 1.0 — 15 categories (order matches the trained label_list).
DOTA_CLASSES = [
    "plane", "baseball-diamond", "bridge", "ground-track-field", "small-vehicle",
    "large-vehicle", "ship", "tennis-court", "basketball-court", "storage-tank",
    "soccer-ball-field", "roundabout", "harbor", "swimming-pool", "helicopter",
]
DOTA_LABELS_ZH = {
    "plane": "飞机", "baseball-diamond": "棒球场", "bridge": "桥梁",
    "ground-track-field": "田径场", "small-vehicle": "小型车辆",
    "large-vehicle": "大型车辆", "ship": "舰船", "tennis-court": "网球场",
    "basketball-court": "篮球场", "storage-tank": "储油罐",
    "soccer-ball-field": "足球场", "roundabout": "环岛", "harbor": "港口",
    "swimming-pool": "游泳池", "helicopter": "直升机",
}
# Distinct RGB per class for burned overlay.
CLASS_COLORS = [
    (230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48),
    (145, 30, 180), (70, 240, 240), (240, 50, 230), (210, 245, 60), (250, 190, 212),
    (0, 128, 128), (220, 190, 255), (170, 110, 40), (255, 250, 200), (128, 0, 0),
]


def compute(
    *,
    input_path: str,
    output_dir: str,
    red_band: int = 1,
    green_band: int = 2,
    blue_band: int = 3,
    score_threshold: float = 0.5,
) -> dict[str, Any]:
    inp = Path(input_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rgb, (height, width) = _read_rgb(inp, red_band, green_band, blue_band)
    detections = _run_inference(rgb, score_threshold)

    output_png = "detection_overlay.png"
    _render_overlay(detections, width, height, out / output_png)

    counts: dict[str, int] = {}
    for det in detections:
        counts[det["class_name"]] = counts.get(det["class_name"], 0) + 1

    classes = [
        {
            "name": name,
            "label": DOTA_LABELS_ZH.get(name, name),
            "count": counts[name],
            "color": "#%02x%02x%02x" % CLASS_COLORS[DOTA_CLASSES.index(name)],
        }
        for name in sorted(counts, key=lambda n: counts[n], reverse=True)
    ]
    result = {
        "output_png": output_png,
        "detection_count": len(detections),
        "score_threshold": score_threshold,
        "classes": classes,
    }
    (out / "detection_stats.json").write_text(json.dumps(result), encoding="utf-8")
    return result


def _read_rgb(path: Path, red: int, green: int, blue: int) -> tuple[np.ndarray, tuple[int, int]]:
    with rasterio.open(path) as src:
        for name, band in ("red", red), ("green", green), ("blue", blue):
            if band < 1 or band > src.count:
                raise ValueError(f"{name}_band={band} 超出影像波段范围（共 {src.count} 个波段）")
        bands = [src.read(b).astype(np.float32) for b in (red, green, blue)]
    stacked = np.stack(bands, axis=-1)
    # Per-channel 2–98 percentile stretch to 8-bit (handles 16-bit imagery).
    out = np.zeros_like(stacked, dtype=np.uint8)
    for c in range(3):
        chan = stacked[..., c]
        finite = chan[np.isfinite(chan)]
        if finite.size == 0:
            continue
        lo, hi = np.percentile(finite, (2, 98))
        if hi <= lo:
            hi = lo + 1.0
        out[..., c] = np.clip((chan - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
    return out, (out.shape[0], out.shape[1])


def _run_inference(rgb: np.ndarray, score_threshold: float) -> list[dict[str, Any]]:
    """Run PP-YOLOE-R via PaddleDetection's deploy predictor on an in-memory RGB array."""
    import cv2  # noqa: F401  (paddle deploy pipeline imports cv2 internally)
    import paddle

    paddledet_dir = os.environ.get("PADDLEDET_DIR", "/app/PaddleDetection")
    model_dir = os.environ.get("RS_DETECT_MODEL_DIR")
    if not model_dir or not Path(model_dir).exists():
        raise RuntimeError(f"检测模型目录不存在: {model_dir}")

    # GPU when available, else CPU (the GPU image ships CPU kernels too).
    device = "GPU" if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0 else "CPU"
    paddle.set_device("gpu" if device == "GPU" else "cpu")

    sys.path.insert(0, str(Path(paddledet_dir) / "deploy" / "python"))
    from infer import Detector  # type: ignore

    detector = Detector(model_dir, device=device, threshold=score_threshold)
    # Detector expects BGR uint8 (cv2 convention).
    bgr = rgb[..., ::-1].copy()
    results = detector.predict_image([bgr], visual=False)
    boxes = np.asarray(results.get("boxes", []))
    detections: list[dict[str, Any]] = []
    for row in boxes:
        # Rotated-box output rows: [class_id, score, x1,y1,x2,y2,x3,y3,x4,y4]
        if len(row) < 10:
            continue
        class_id, score = int(row[0]), float(row[1])
        if score < score_threshold or class_id < 0 or class_id >= len(DOTA_CLASSES):
            continue
        detections.append(
            {
                "class_id": class_id,
                "class_name": DOTA_CLASSES[class_id],
                "score": score,
                "polygon": [float(v) for v in row[2:10]],
            }
        )
    return detections


def _render_overlay(detections: list[dict[str, Any]], width: int, height: int, out_path: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    for det in detections:
        color = CLASS_COLORS[det["class_id"]]
        pts = det["polygon"]
        polygon = [(pts[i], pts[i + 1]) for i in range(0, 8, 2)]
        draw.polygon(polygon, outline=(*color, 255), width=3)
    if max(image.size) > 2048:
        image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
    image.save(out_path, optimize=True)

"""YOLO11s-OBB tiled detection over a raster, rendered as a transparent PNG overlay."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4
from contextlib import redirect_stdout

import numpy as np
import rasterio

# Public DOTA 1.0 class order; the inference adapter maps checkpoint labels by name.
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
    from tiled_obb import infer
    # stdout is reserved for JSON-RPC; model logs must go to stderr.
    with redirect_stdout(sys.stderr):
        detections, runtime = infer(rgb, score_threshold, DOTA_CLASSES)
    with rasterio.open(inp) as src:
        valid = src.dataset_mask() > 0
        def valid_center(det):
            points = np.asarray(det["polygon"]).reshape(4, 2)
            x, y = points.mean(axis=0)
            return 0 <= x < width and 0 <= y < height and valid[int(y), int(x)]
        detections = [det for det in detections if valid_center(det)]
        grid = {"width": width, "height": height, "pixel_size": list(src.res),
                "crs": str(src.crs) if src.crs else None, "transform": list(src.transform)[:6]}
        features = []
        if src.crs:
            from rasterio.warp import transform
            for det in detections:
                pixels = np.asarray(det["polygon"]).reshape(4, 2)
                xy = [src.transform * tuple(point) for point in pixels]
                lon, lat = transform(src.crs, "EPSG:4326", [p[0] for p in xy], [p[1] for p in xy])
                ring = [list(pair) for pair in zip(lon, lat)]
                ring.append(ring[0])
                features.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                                 "properties": {k: v for k, v in det.items() if k != "polygon"}})
    suffix = uuid4().hex[:16]
    output_json = f"detection_{suffix}.json"
    output_geojson = f"detection_{suffix}.geojson" if grid["crs"] else None
    if output_geojson:
        (out / output_geojson).write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")

    output_png = f"detection_{suffix}.png"
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
        "output_json": output_json,
        "output_geojson": output_geojson,
        "model_name": "YOLO11s-OBB / DOTA 15 类",
        "model_sha256": "43fa63102922e0701501241b307420d24fc55e080816888b18bf8c6f96b1a45a",
        "bands_used": [red_band, green_band, blue_band],
        "analysis_grid": grid, "width": width, "height": height,
        **runtime,
        "detection_count": len(detections),
        "score_threshold": score_threshold,
        "classes": classes,
    }
    (out / output_json).write_text(json.dumps({**result, "detections": detections}), encoding="utf-8")
    return result


def _read_rgb(path: Path, red: int, green: int, blue: int) -> tuple[np.ndarray, tuple[int, int]]:
    with rasterio.open(path) as src:
        for name, band in ("red", red), ("green", green), ("blue", blue):
            if band < 1 or band > src.count:
                raise ValueError(f"{name}_band={band} 超出影像波段范围（共 {src.count} 个波段）")
        bands = [src.read(b) for b in (red, green, blue)]
        valid_mask = src.dataset_mask() > 0
    if all(band.dtype == np.uint8 for band in bands):
        rgb = np.stack(bands, axis=-1)
        rgb[~valid_mask] = 0
        return rgb, rgb.shape[:2]
    stacked = np.stack(bands, axis=-1)
    # Per-channel 2–98 percentile stretch to 8-bit (handles 16-bit imagery).
    out = np.zeros_like(stacked, dtype=np.uint8)
    for c in range(3):
        chan = stacked[..., c]
        finite = chan[np.isfinite(chan) & valid_mask]
        if finite.size == 0:
            continue
        lo, hi = np.percentile(finite, (2, 98))
        if hi <= lo:
            hi = lo + 1.0
        out[..., c] = np.clip((chan - lo) / (hi - lo) * 255.0, 0, 255).astype(np.uint8)
    out[~valid_mask] = 0
    return out, (out.shape[0], out.shape[1])


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

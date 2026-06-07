"""U-Net (LandCover.ai) land-cover semantic segmentation over a raster.

Reads an RGB composite from a (possibly multi-band, 16-bit) raster, runs the
trained segmentation-models-pytorch U-Net by sliding overlapping 512 patches,
and renders a transparent colored mask PNG plus per-class pixel statistics.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import rasterio

# The shipped checkpoint is trained on these 4 classes (train_classes), in this
# channel order. argmax over the model's 4 output channels maps to these indices.
CLASSES = ["background", "building", "woodland", "water"]
CLASS_LABELS_ZH = {
    "background": "背景",
    "building": "建筑",
    "woodland": "林地",
    "water": "水体",
}
# RGBA overlay colors; background is fully transparent so the basemap shows through.
CLASS_COLORS = {
    "background": (0, 0, 0, 0),
    "building": (230, 25, 75, 180),
    "woodland": (60, 180, 75, 180),
    "water": (0, 130, 200, 180),
}

PATCH_SIZE = 512
ENCODER = "efficientnet-b0"
ENCODER_WEIGHTS = "imagenet"


def compute(
    *,
    input_path: str,
    output_dir: str,
    red_band: int = 1,
    green_band: int = 2,
    blue_band: int = 3,
) -> dict[str, Any]:
    inp = Path(input_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    rgb = _read_rgb(inp, red_band, green_band, blue_band)
    pred_mask = _run_inference(rgb)

    output_png = "segmentation_overlay.png"
    _render_overlay(pred_mask, out / output_png)

    total = int(pred_mask.size)
    classes = []
    for idx, name in enumerate(CLASSES):
        count = int(np.count_nonzero(pred_mask == idx))
        if count == 0:
            continue
        classes.append(
            {
                "name": name,
                "label": CLASS_LABELS_ZH.get(name, name),
                "pixel_count": count,
                "percentage": round(count / total * 100.0, 4) if total else 0.0,
                "color": "#%02x%02x%02x" % CLASS_COLORS[name][:3],
            }
        )
    classes.sort(key=lambda c: c["pixel_count"], reverse=True)

    result = {
        "output_png": output_png,
        "total_pixels": total,
        "classes": classes,
    }
    (out / "segmentation_stats.json").write_text(json.dumps(result), encoding="utf-8")
    return result


def _read_rgb(path: Path, red: int, green: int, blue: int) -> np.ndarray:
    """Read 3 bands as an 8-bit RGB array using per-channel 2-98 percentile stretch."""
    with rasterio.open(path) as src:
        for name, band in ("red", red), ("green", green), ("blue", blue):
            if band < 1 or band > src.count:
                raise ValueError(f"{name}_band={band} 超出影像波段范围（共 {src.count} 个波段）")
        bands = [src.read(b).astype(np.float32) for b in (red, green, blue)]
    stacked = np.stack(bands, axis=-1)
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
    return out


def _run_inference(rgb: np.ndarray) -> np.ndarray:
    """Slide overlapping PATCH_SIZE windows through the U-Net; return a class-index mask."""
    import segmentation_models_pytorch as smp
    import torch
    from patchify import patchify, unpatchify

    model_path = os.environ.get("RS_SEGMENT_MODEL_PATH")
    if not model_path or not Path(model_path).exists():
        raise RuntimeError(f"分割模型权重不存在: {model_path}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = torch.load(model_path, map_location=torch.device(device))
    model.eval()
    preprocessing_fn = smp.encoders.get_preprocessing_fn(ENCODER, ENCODER_WEIGHTS)

    height, width = rgb.shape[:2]
    pad_h = (math.ceil(height / PATCH_SIZE) * PATCH_SIZE) - height
    pad_w = (math.ceil(width / PATCH_SIZE) * PATCH_SIZE) - width
    padded = np.pad(rgb, ((0, pad_h), (0, pad_w), (0, 0)), mode="reflect")

    step = PATCH_SIZE // 2
    patches = patchify(padded, (PATCH_SIZE, PATCH_SIZE, 3), step=step)[:, :, 0, :, :, :]
    mask_patches = np.empty(patches.shape[:-1], dtype=np.uint8)
    with torch.no_grad():
        for i in range(patches.shape[0]):
            for j in range(patches.shape[1]):
                patch = preprocessing_fn(patches[i, j]).transpose(2, 0, 1).astype("float32")
                tensor = torch.from_numpy(patch).to(device).unsqueeze(0)
                pred = model.predict(tensor).squeeze().cpu().numpy().round()
                mask_patches[i, j] = pred.transpose(1, 2, 0).argmax(2).astype(np.uint8)

    full = unpatchify(mask_patches, padded.shape[:-1])
    return full[:height, :width]


def _render_overlay(mask: np.ndarray, out_path: Path) -> None:
    from PIL import Image

    height, width = mask.shape[:2]
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    for idx, name in enumerate(CLASSES):
        rgba[mask == idx] = CLASS_COLORS[name]
    image = Image.fromarray(rgba, mode="RGBA")
    if max(image.size) > 2048:
        image.thumbnail((2048, 2048), Image.Resampling.NEAREST)
    image.save(out_path, optimize=True)



"""U-Net (LandCover.ai) land-cover semantic segmentation over a raster.

Reads an RGB composite from a (possibly multi-band, 16-bit) raster, runs the
trained segmentation-models-pytorch U-Net by sliding overlapping 512 patches,
and renders a transparent colored mask PNG plus per-class pixel statistics.
"""

from __future__ import annotations

import json
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

# 分类掩膜渲染缩放上限。掩膜必须用 NEAREST 重采样——任何插值都会在类别边界
# 造出不存在的中间类别（如 building↔water 之间插出 woodland），故这不是 bug。
RENDER_MAX_SIZE = 2048
# 后处理：小连通域过滤阈值。面积 < max(下限, 图面积/除数) 的非背景碎斑降为背景。
# 下限保证极小图也能去掉单像素噪点；除数让阈值随图尺寸自适应。
MIN_BLOB_SIZE_FLOOR = 64
BLOB_AREA_DIVISOR = 5000


# ----- 以下为不依赖 torch 的纯 numpy 函数（可独立单测）-------------------------


def _cosine_window(size: int) -> np.ndarray:
    """2D 余弦（Hann 型）权重窗，中心权重最大、边缘趋零但严格 >0。

    用于分块推理的重叠区软融合：相邻块在重叠处按各自余弦权重加权平均，
    边缘趋零使过渡平滑、消除硬拼接接缝。端点取 (n+1)/(size+1) 而非 n/(size-1)，
    保证处处 >0——单块覆盖时权重可在归一化中被精确约掉，不放大噪声。
    """
    n = np.arange(size, dtype=np.float64)
    w1d = 0.5 * (1.0 - np.cos(2.0 * np.pi * (n + 1.0) / (size + 1.0)))
    return np.outer(w1d, w1d).astype(np.float32)


def _softmax(logits: np.ndarray, axis: int = -1) -> np.ndarray:
    """数值稳定 softmax；把模型每像素的类别打分转成可加权融合的概率分布。"""
    shifted = logits - np.max(logits, axis=axis, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=axis, keepdims=True)


def _majority_filter(mask: np.ndarray, num_classes: int) -> np.ndarray:
    """3×3 邻域众数滤波：消除椒盐噪声、平滑锯齿边界。类别数少，用 one-hot 计票。

    平票时 argmax 取最小类别索引（背景=0 优先），倾向保守不误升类别。
    """
    height, width = mask.shape
    padded = np.pad(mask, 1, mode="edge")
    votes = np.zeros((height, width, num_classes), dtype=np.int32)
    for dy in range(3):
        for dx in range(3):
            window = padded[dy : dy + height, dx : dx + width]
            for cls in range(num_classes):
                votes[..., cls] += (window == cls).astype(np.int32)
    return votes.argmax(axis=-1).astype(np.uint8)


def _label_connected(binary: np.ndarray) -> np.ndarray:
    """4-邻接连通域标记（纯 numpy 迭代标签传播，至收敛）。

    每个前景像素初始化为唯一 id，反复向 4 邻域取 max 传播，域内收敛到该域最大 id。
    label 单调不减且有界，必收敛。大图可改用 scipy.ndimage.label 加速（此处避免引入依赖）。
    """
    height, width = binary.shape
    labels = np.where(
        binary, np.arange(1, binary.size + 1).reshape(binary.shape), 0
    ).astype(np.int64)
    while True:
        prev = labels.copy()
        nbr = labels.copy()
        nbr[1:, :] = np.maximum(nbr[1:, :], labels[:-1, :])
        nbr[:-1, :] = np.maximum(nbr[:-1, :], labels[1:, :])
        nbr[:, 1:] = np.maximum(nbr[:, 1:], labels[:, :-1])
        nbr[:, :-1] = np.maximum(nbr[:, :-1], labels[:, 1:])
        labels = np.where(binary, nbr, 0)
        if np.array_equal(labels, prev):
            return labels


def _remove_small_blobs(mask: np.ndarray, min_size: int, num_classes: int) -> np.ndarray:
    """逐非背景类做连通域过滤，面积 < min_size 的碎斑降为背景（=透明，视觉去碎）。

    降为背景而非回填周边类：小斑本就是低置信误判，归背景最保守、不臆造类别。
    """
    out = mask.copy()
    for cls in range(1, num_classes):
        binary = mask == cls
        if not binary.any():
            continue
        labels = _label_connected(binary)
        counts = np.bincount(labels.ravel())
        small = np.where(counts < min_size)[0]
        small = small[small > 0]
        if small.size:
            out[np.isin(labels, small)] = 0
    return out


def _postprocess(mask: np.ndarray, num_classes: int) -> np.ndarray:
    """分类掩膜后处理：先众数滤波去椒盐/平滑边界，再连通域过滤去中等碎斑。

    只动空间形态、不改类别语义；解决朴素推理输出的"破碎状小斑块"问题。
    """
    height, width = mask.shape
    min_size = max(MIN_BLOB_SIZE_FLOOR, int(height * width / BLOB_AREA_DIVISOR))
    smoothed = _majority_filter(mask, num_classes)
    return _remove_small_blobs(smoothed, min_size, num_classes)



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
    """滑窗 U-Net 推理：重叠块按余弦窗加权融合概率，再 argmax + 后处理。

    取代旧的"每块 argmax 后 unpatchify 硬覆盖"——硬覆盖丢弃重叠区信息、留下拼接
    接缝。此处累积 softmax 概率 × 余弦窗，重叠处平滑过渡，无接缝；融合后整图一次
    argmax，再做形态学后处理去碎斑。
    """
    import segmentation_models_pytorch as smp
    import torch

    model_path = os.environ.get("RS_SEGMENT_MODEL_PATH")
    if not model_path or not Path(model_path).exists():
        raise RuntimeError(f"分割模型权重不存在: {model_path}")

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = torch.load(model_path, map_location=torch.device(device))
    model.eval()
    preprocessing_fn = smp.encoders.get_preprocessing_fn(ENCODER, ENCODER_WEIGHTS)

    height, width = rgb.shape[:2]
    # pad 到至少一个 PATCH_SIZE 且为 step 的整数步覆盖；reflect 避免边缘黑边干扰推理。
    pad_h = max(0, PATCH_SIZE - height) + (PATCH_SIZE - height % PATCH_SIZE) % PATCH_SIZE
    pad_w = max(0, PATCH_SIZE - width) + (PATCH_SIZE - width % PATCH_SIZE) % PATCH_SIZE
    padded = np.pad(rgb, ((0, pad_h), (0, pad_w), (0, 0)), mode="reflect")
    pad_height, pad_width = padded.shape[:2]

    num_classes = len(CLASSES)
    window = _cosine_window(PATCH_SIZE)
    prob_acc = np.zeros((pad_height, pad_width, num_classes), dtype=np.float32)
    weight_acc = np.zeros((pad_height, pad_width), dtype=np.float32)

    step = PATCH_SIZE // 2  # 50% 重叠：融合质量足够，且不像更小 step 那样翻倍推理量。
    ys = list(range(0, pad_height - PATCH_SIZE + 1, step))
    xs = list(range(0, pad_width - PATCH_SIZE + 1, step))
    # 末块对齐到右/下边缘，保证贴边区域被覆盖（步长不整除时尾巴不漏）。
    if ys[-1] != pad_height - PATCH_SIZE:
        ys.append(pad_height - PATCH_SIZE)
    if xs[-1] != pad_width - PATCH_SIZE:
        xs.append(pad_width - PATCH_SIZE)

    with torch.no_grad():
        for y in ys:
            for x in xs:
                patch = padded[y : y + PATCH_SIZE, x : x + PATCH_SIZE]
                arr = preprocessing_fn(patch).transpose(2, 0, 1).astype("float32")
                tensor = torch.from_numpy(arr).to(device).unsqueeze(0)
                logits = model.predict(tensor).squeeze(0).cpu().numpy()  # [C,H,W]
                prob = _softmax(logits.transpose(1, 2, 0), axis=-1)  # [H,W,C]
                prob_acc[y : y + PATCH_SIZE, x : x + PATCH_SIZE] += prob * window[..., None]
                weight_acc[y : y + PATCH_SIZE, x : x + PATCH_SIZE] += window

    # 归一化（weight_acc 处处 >0，因余弦窗严格正且每像素至少被一块覆盖）。
    fused = prob_acc / np.maximum(weight_acc, 1e-8)[..., None]
    mask = fused.argmax(axis=-1).astype(np.uint8)[:height, :width]
    return _postprocess(mask, num_classes)


def _render_overlay(mask: np.ndarray, out_path: Path) -> None:
    from PIL import Image

    height, width = mask.shape[:2]
    rgba = np.zeros((height, width, 4), dtype=np.uint8)
    for idx, name in enumerate(CLASSES):
        rgba[mask == idx] = CLASS_COLORS[name]
    image = Image.fromarray(rgba, mode="RGBA")
    if max(image.size) > RENDER_MAX_SIZE:
        # 掩膜缩放必须 NEAREST：插值会在类别边界造出不存在的中间类别。
        image.thumbnail((RENDER_MAX_SIZE, RENDER_MAX_SIZE), Image.Resampling.NEAREST)
    image.save(out_path, optimize=True)



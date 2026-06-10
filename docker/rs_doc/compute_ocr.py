from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio


# OCR 引擎单例：RapidOCR 初始化（加载 det/rec/cls ONNX 模型）开销较大，
# 同一进程内复用。容器是一次性进程，单例足够。
_OCR_ENGINE: Any = None


def compute(
    *,
    input_path: str,
    output_dir: str,
    red_band: int = 1,
    green_band: int = 2,
    blue_band: int = 3,
    grayscale: bool = False,
    max_dimension: int = 2048,
    min_confidence: float = 0.0,
) -> dict[str, Any]:
    """对 GeoTIFF 影像做光学字符识别（RapidOCR / PP-OCRv4，中英文）。

    流程：
    - rasterio 读取指定波段，组成 RGB（grayscale=True 时只用 red_band 做灰度）。
    - 按 2%~98% 百分位拉伸把任意位深/动态范围归一化到 8bit，OCR 引擎只认 8bit 图像。
    - 超大图按 max_dimension 等比缩小，控制识别耗时与内存。
    - RapidOCR 识别，返回每个文本块的文字、置信度、四点框；按 min_confidence 过滤。

    返回 dict（structuredContent），不抛业务异常时含 full_text/blocks/统计。
    """
    inp = Path(input_path)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if not inp.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    with rasterio.open(inp) as src:
        band_count = src.count
        _validate_bands(
            band_count,
            red=red_band,
            green=green_band,
            blue=blue_band,
            grayscale=grayscale,
        )
        if grayscale or band_count == 1:
            gray = src.read(1 if band_count == 1 else red_band).astype(np.float32)
            rgb8 = _to_8bit(gray)
            image = np.stack([rgb8, rgb8, rgb8], axis=-1)
        else:
            red = _to_8bit(src.read(red_band).astype(np.float32))
            green = _to_8bit(src.read(green_band).astype(np.float32))
            blue = _to_8bit(src.read(blue_band).astype(np.float32))
            image = np.stack([red, green, blue], axis=-1)

    image = _downscale(image, max_dimension)

    ocr = _engine()
    raw, _elapse = ocr(image)
    blocks = _normalize_blocks(raw, min_confidence=min_confidence)

    full_text = "\n".join(block["text"] for block in blocks)
    confidences = [block["confidence"] for block in blocks]
    avg_conf = round(float(np.mean(confidences)), 4) if confidences else 0.0
    min_conf = round(float(np.min(confidences)), 4) if confidences else 0.0

    stats: dict[str, Any] = {
        "full_text": full_text,
        "blocks": blocks,
        "block_count": len(blocks),
        "char_count": len(full_text),
        "avg_confidence": avg_conf,
        "min_confidence_seen": min_conf,
        "min_confidence_filter": round(float(min_confidence), 4),
        "image_height": int(image.shape[0]),
        "image_width": int(image.shape[1]),
        "grayscale": bool(grayscale or band_count == 1),
        "engine": "rapidocr_onnxruntime/PP-OCRv4",
    }
    (out / "ocr_result.json").write_text(
        json.dumps(stats, ensure_ascii=False), encoding="utf-8"
    )
    return stats


def _validate_bands(
    count: int, *, red: int, green: int, blue: int, grayscale: bool
) -> None:
    if grayscale or count == 1:
        bands = {"red": red} if count != 1 else {}
    else:
        bands = {"red": red, "green": green, "blue": blue}
    for name, band in bands.items():
        if band < 1:
            raise ValueError(f"{name}_band must be >= 1, got {band}")
        if band > count:
            raise ValueError(
                f"ocr_recognize requires {name}_band={band}, but imagery has {count} bands"
            )


def _to_8bit(band: np.ndarray) -> np.ndarray:
    """按 2%~98% 百分位拉伸归一化到 uint8，对任意位深/动态范围稳健。"""
    finite = band[np.isfinite(band)]
    if finite.size == 0:
        return np.zeros(band.shape, dtype=np.uint8)
    lo = float(np.percentile(finite, 2))
    hi = float(np.percentile(finite, 98))
    if hi <= lo:
        lo = float(finite.min())
        hi = float(finite.max())
    if hi <= lo:
        return np.zeros(band.shape, dtype=np.uint8)
    clipped = np.clip(band, lo, hi)
    scaled = (clipped - lo) / (hi - lo) * 255.0
    return np.nan_to_num(scaled, nan=0.0).astype(np.uint8)


def _downscale(image: np.ndarray, max_dimension: int) -> np.ndarray:
    height, width = image.shape[0], image.shape[1]
    longest = max(height, width)
    if max_dimension <= 0 or longest <= max_dimension:
        return image
    from PIL import Image

    scale = max_dimension / float(longest)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    resized = Image.fromarray(image, mode="RGB").resize(
        new_size, Image.Resampling.LANCZOS
    )
    return np.asarray(resized)


def _normalize_blocks(raw: Any, *, min_confidence: float) -> list[dict[str, Any]]:
    """把 RapidOCR 输出 [[box, text, score], ...] 归一为稳定结构，按置信度过滤。

    RapidOCR 无文字时返回 None。
    """
    if not raw:
        return []
    blocks: list[dict[str, Any]] = []
    for item in raw:
        try:
            box, text, score = item[0], item[1], item[2]
        except (TypeError, IndexError, ValueError):
            continue
        confidence = float(score)
        if confidence < min_confidence:
            continue
        text_str = str(text).strip()
        if not text_str:
            continue
        blocks.append(
            {
                "text": text_str,
                "confidence": round(confidence, 4),
                "box": [[float(x), float(y)] for x, y in box],
            }
        )
    return blocks


def _engine() -> Any:
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE

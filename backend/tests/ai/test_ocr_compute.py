import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_DOC_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_doc"
sys.path.insert(0, str(RS_DOC_DIR))

from compute_ocr import (  # noqa: E402
    _downscale,
    _normalize_blocks,
    _to_8bit,
    _validate_bands,
    compute,
)


def _write_tif(path: Path, data: np.ndarray, *, nodata=None) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[1],
        width=data.shape[2],
        count=data.shape[0],
        dtype=str(data.dtype),
        nodata=nodata,
        transform=from_origin(0, data.shape[1], 1, 1),
    ) as dst:
        dst.write(data)


# ---------- 纯函数：归一化 / 缩放 / 波段校验 / 结果解析（不依赖 OCR 引擎）----------

def test_to_8bit_normalizes_high_bit_depth() -> None:
    # uint16 渐变应被拉伸到 0-255 区间。
    band = np.arange(0, 10000, 100, dtype=np.float32).reshape(10, 10)
    out = _to_8bit(band)
    assert out.dtype == np.uint8
    assert out.min() == 0
    assert out.max() == 255


def test_to_8bit_handles_flat_band() -> None:
    # 常数波段（hi<=lo）应安全返回全 0，不抛除零。
    band = np.full((4, 4), 1234.0, dtype=np.float32)
    out = _to_8bit(band)
    assert out.dtype == np.uint8
    assert int(out.max()) == 0


def test_to_8bit_handles_all_nan() -> None:
    band = np.full((3, 3), np.nan, dtype=np.float32)
    out = _to_8bit(band)
    assert out.dtype == np.uint8
    assert int(out.max()) == 0


def test_downscale_shrinks_oversized_image() -> None:
    image = np.zeros((100, 400, 3), dtype=np.uint8)
    out = _downscale(image, 200)
    # 最长边 400 -> 200，等比缩放。
    assert max(out.shape[0], out.shape[1]) == 200
    assert out.shape[2] == 3


def test_downscale_keeps_small_image_untouched() -> None:
    image = np.zeros((50, 60, 3), dtype=np.uint8)
    out = _downscale(image, 200)
    assert out.shape == image.shape


def test_validate_bands_rejects_out_of_range() -> None:
    with pytest.raises(ValueError, match="ocr_recognize requires"):
        _validate_bands(3, red=1, green=2, blue=9, grayscale=False)


def test_validate_bands_rejects_below_one() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        _validate_bands(3, red=0, green=2, blue=3, grayscale=False)


def test_validate_bands_grayscale_only_checks_red() -> None:
    # 灰度模式：blue 越界也不应报错（只用 red_band）。
    _validate_bands(3, red=1, green=2, blue=99, grayscale=True)


def test_validate_bands_single_band_image_ok() -> None:
    # 单波段影像即使非灰度请求也按灰度处理，不校验三波段。
    _validate_bands(1, red=1, green=2, blue=3, grayscale=False)


def test_normalize_blocks_filters_low_confidence() -> None:
    raw = [
        [[[0, 0], [1, 0], [1, 1], [0, 1]], "保留", 0.9],
        [[[0, 0], [1, 0], [1, 1], [0, 1]], "丢弃", 0.3],
        [[[0, 0], [1, 0], [1, 1], [0, 1]], "   ", 0.99],  # 空白文本剔除
    ]
    blocks = _normalize_blocks(raw, min_confidence=0.5)
    assert len(blocks) == 1
    assert blocks[0]["text"] == "保留"
    assert blocks[0]["confidence"] == 0.9
    assert len(blocks[0]["box"]) == 4


def test_normalize_blocks_handles_none() -> None:
    # RapidOCR 无文字时返回 None。
    assert _normalize_blocks(None, min_confidence=0.0) == []


def test_normalize_blocks_skips_malformed_items() -> None:
    raw = [["only_one_field"], [[[0, 0]], "ok", 0.8]]
    blocks = _normalize_blocks(raw, min_confidence=0.0)
    assert len(blocks) == 1
    assert blocks[0]["text"] == "ok"


def test_compute_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compute(input_path=str(tmp_path / "nope.tif"), output_dir=str(tmp_path / "out"))


def test_compute_rejects_out_of_range_band(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    _write_tif(input_path, np.ones((3, 4, 4), dtype=np.uint16))
    with pytest.raises(ValueError, match="ocr_recognize requires"):
        compute(
            input_path=str(input_path),
            output_dir=str(tmp_path / "out"),
            blue_band=9,
        )


# ---------- 端到端：真实 RapidOCR 引擎（本机无引擎则跳过；docker 构建期已验证）----------

def test_compute_ocr_end_to_end(tmp_path: Path) -> None:
    pytest.importorskip("rapidocr_onnxruntime")
    from PIL import Image, ImageDraw

    # 合成一张带清晰英文的 RGB GeoTIFF（白底黑字）。
    width, height = 400, 100
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 35), "RS AGENT 2026", fill="black")
    arr = np.asarray(img).transpose(2, 0, 1).astype(np.uint8)  # (3, H, W)

    input_path = tmp_path / "scan.tif"
    output_dir = tmp_path / "out"
    _write_tif(input_path, arr)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    assert (output_dir / "ocr_result.json").exists()
    assert stats["block_count"] >= 1
    # 识别全文里应能找到我们写入的关键 token（大小写/空格可能有出入）。
    recognized = stats["full_text"].upper().replace(" ", "")
    assert "RS" in recognized or "2026" in recognized
    assert 0.0 <= stats["avg_confidence"] <= 1.0

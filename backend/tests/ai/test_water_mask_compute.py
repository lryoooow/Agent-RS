import re
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

from compute_water_mask import NODATA, NON_WATER, WATER, compute  # noqa: E402


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
        dst.update_tags(REFL_SCALE=".0001" if data.dtype.kind in "iu" else "1", REFL_OFFSET="0", REFL_SOURCE="synthetic_fixture")


def _ndwi_image(water_frac: float, size: int = 10, seed: int = 11) -> np.ndarray:
    """构造连续 NDWI 分布的 4 波段 DN 影像。

    水体像元 NDWI ~ U(0.05, 0.95)（浑浊度/水深不同，NDWI 不会是单值——
    历史上退化的两级 NDWI 测试数据恰好落在分位数间隙，测不出 85 分位封顶 bug）。
    由 NDWI 反解 green/nir：nir=1000, green = nir*(1+ndwi)/(1-ndwi)。
    水体像元占据展平后的前 water_frac*size*size 个位置，占比精确可控。
    """
    rng = np.random.default_rng(seed)
    total = size * size
    water_count = round(water_frac * total)
    ndwi = np.concatenate([
        rng.uniform(0.05, 0.95, water_count),
        rng.uniform(-0.95, -0.05, total - water_count),
    ])
    nir = np.full(total, 1000.0)
    green = nir * (1 + ndwi) / (1 - ndwi)
    green = green.reshape(size, size).astype(np.uint16)
    nir = nir.reshape(size, size).astype(np.uint16)
    return np.stack([green, green, green, nir]).astype(np.uint16)


def test_compute_water_mask_detects_water_row(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    # 4 波段 (blue,green,red,nir)。顶行为水体(高 NDWI: green>>nir)，其余为陆地(负 NDWI)。
    h, w = 4, 4
    blue = np.full((h, w), 100, dtype=np.uint16)
    green = np.full((h, w), 100, dtype=np.uint16)
    red = np.full((h, w), 100, dtype=np.uint16)
    nir = np.full((h, w), 300, dtype=np.uint16)  # 陆地: green<nir -> NDWI 负

    green[0, :] = 300  # 顶行水体: green=300, nir=100 -> NDWI=0.5
    nir[0, :] = 100

    data = np.stack([blue, green, red, nir]).astype(np.uint16)
    _write_tif(input_path, data)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    assert (output_dir / stats["output_tif"]).exists()
    assert (output_dir / stats["output_png"]).exists()
    assert re.fullmatch(r"water_mask_[0-9a-f]{16}\.tif", stats["output_tif"])
    assert re.fullmatch(r"water_mask_[0-9a-f]{16}_colored\.png", stats["output_png"])
    assert list(output_dir.glob("water_mask_*_stats.json"))

    total_pct = stats["water_pct"] + stats["non_water_pct"] + stats["nodata_pct"]
    assert abs(total_pct - 100.0) < 0.5

    with rasterio.open(output_dir / stats["output_tif"]) as src:
        classification = src.read(1)
        assert src.dtypes[0] == "uint8"

    # 顶行应判为水体，其余为非水体
    assert np.all(classification[0, :] == WATER)
    assert np.all(classification[1:, :] == NON_WATER)
    assert set(np.unique(classification)).issubset({NON_WATER, WATER, NODATA})


def test_compute_water_mask_no_water_when_all_land(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    # 全部陆地: green < nir -> NDWI 全负，阈值法不应误报水体。
    h, w = 3, 3
    blue = np.full((h, w), 100, dtype=np.uint16)
    green = np.full((h, w), 80, dtype=np.uint16)
    red = np.full((h, w), 120, dtype=np.uint16)
    nir = np.full((h, w), 400, dtype=np.uint16)
    data = np.stack([blue, green, red, nir]).astype(np.uint16)
    _write_tif(input_path, data)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    assert stats["water_pct"] == 0.0
    with rasterio.open(output_dir / stats["output_tif"]) as src:
        classification = src.read(1)
    assert not np.any(classification == WATER)


def test_compute_water_mask_marks_nodata(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.full((4, 2, 2), 200, dtype=np.uint16)
    data[:, 0, 0] = 0  # 一个像素 green/nir 为 0 -> nodata
    _write_tif(input_path, data, nodata=0)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    with rasterio.open(output_dir / stats["output_tif"]) as src:
        classification = src.read(1)

    assert classification[0, 0] == NODATA
    assert stats["nodata_pct"] == 25.0


# ---------- A1：物理阈值（McFeeters NDWI > threshold），分位封顶修复 ----------


@pytest.mark.parametrize("water_frac", [0.0, 0.15, 0.50, 0.60, 1.00])
def test_compute_water_mask_reports_true_water_fraction(tmp_path: Path, water_frac: float) -> None:
    """正常/回归：水体占比 0/15/50/60/100% 时 water_pct 误差 ≤ 1 个百分点。

    回归锁定（历史 bug：85 分位阈值把水体占比封顶在 ~15%，60% 水体只能报
    15.0%——2026-10-07 工作单 A1）。修复后阈值是物理值 0.0（McFeeters NDWI），
    与水体占比无关。
    """
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, _ndwi_image(water_frac))

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    expected_pct = water_frac * 100.0
    assert abs(stats["water_pct"] - expected_pct) <= 1.0
    assert stats["threshold_method"] == "fixed_ndwi"
    assert stats["threshold_value"] == 0.0
    assert stats["ndwi_threshold"] == 0.0


def test_compute_water_mask_threshold_parameter_is_honored(tmp_path: Path) -> None:
    """正常：threshold 参数从 schema 暴露并生效。

    手算：land 像元 green=80/nir=400 -> NDWI=(80-400)/480=-2/3；
    把 threshold 设为 -0.9 时该像元应判为水体。
    """
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    green = np.full((2, 2), 80, dtype=np.uint16)
    nir = np.full((2, 2), 400, dtype=np.uint16)
    _write_tif(input_path, np.stack([green, green, green, nir]).astype(np.uint16))

    stats = compute(input_path=str(input_path), output_dir=str(output_dir), threshold=-0.9)

    assert stats["water_pct"] == 100.0
    assert stats["threshold_value"] == -0.9


def test_compute_water_mask_boundary_pixel_equal_to_threshold_is_not_water(tmp_path: Path) -> None:
    """边界：NDWI 恰好等于阈值的像元判为非水体（严格大于）。"""
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    # green=nir=100 -> NDWI = 0，恰好等于默认阈值 0.0。
    green = np.full((2, 2), 100, dtype=np.uint16)
    nir = np.full((2, 2), 100, dtype=np.uint16)
    _write_tif(input_path, np.stack([green, green, green, nir]).astype(np.uint16))

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    assert stats["water_pct"] == 0.0


def test_compute_water_mask_all_zero_ndwi_image(tmp_path: Path) -> None:
    """边界：全部像元 NDWI = 0（green==nir）-> 全部非水体，不误报。"""
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    green = np.full((3, 3), 250, dtype=np.uint16)
    nir = np.full((3, 3), 250, dtype=np.uint16)
    _write_tif(input_path, np.stack([green, green, green, nir]).astype(np.uint16))

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    assert stats["water_pct"] == 0.0
    assert stats["non_water_pct"] == 100.0


@pytest.mark.parametrize("bad_threshold", [1.5, -1.5, 2.0])
def test_compute_water_mask_rejects_threshold_out_of_range(tmp_path: Path, bad_threshold: float) -> None:
    """非法：threshold 超出 [-1,1] -> compute 层拒绝（schema 层另有校验）。"""
    input_path = tmp_path / "input.tif"
    _write_tif(input_path, _ndwi_image(0.3))

    with pytest.raises(ValueError, match="threshold must be within"):
        compute(
            input_path=str(input_path),
            output_dir=str(tmp_path / "output"),
            threshold=bad_threshold,
        )


def test_compute_water_mask_zero_denominator_pixel_counts_as_invalid(tmp_path: Path) -> None:
    """异常：分母 green+nir=0 的像元不计入任何类别，计入无效。"""
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    green = np.full((2, 2), 0.05, dtype=np.float32)
    nir = np.full((2, 2), 0.01, dtype=np.float32)
    green[0, 0] = 0.0
    nir[0, 0] = 0.0
    _write_tif(input_path, np.stack([green, green, green, nir]).astype(np.float32), nodata=float("nan"))

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))
    with rasterio.open(output_dir / stats["output_tif"]) as src:
        classification = src.read(1)

    assert classification[0, 0] == NODATA
    assert stats["nodata_pct"] == 25.0
    assert stats["water_pct"] == 75.0  # 其余像元 NDWI=(0.05-0.01)/0.06=2/3>0


# ---------- A6：输出文件名带 uuid 后缀，重跑不覆盖 ----------


def test_compute_water_mask_rerun_keeps_previous_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, _ndwi_image(0.4))

    first = compute(input_path=str(input_path), output_dir=str(output_dir))
    first_tif = output_dir / first["output_tif"]
    first_bytes = first_tif.read_bytes()
    second = compute(input_path=str(input_path), output_dir=str(output_dir))

    assert first["output_tif"] != second["output_tif"]
    assert first_tif.exists() and (output_dir / second["output_tif"]).exists()
    assert first_tif.read_bytes() == first_bytes  # 第一次的文件内容不变


# ---------- 原有参数校验 ----------


def test_compute_water_mask_rejects_band_above_count(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, np.ones((4, 2, 2), dtype=np.uint16))

    with pytest.raises(ValueError, match="but imagery has"):
        compute(input_path=str(input_path), output_dir=str(output_dir), nir_band=5)


def test_compute_water_mask_rejects_zero_band(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, np.ones((4, 2, 2), dtype=np.uint16))

    with pytest.raises(ValueError, match="must be >= 1"):
        compute(input_path=str(input_path), output_dir=str(output_dir), green_band=0)


def test_compute_water_mask_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compute(input_path=str(tmp_path / "nope.tif"), output_dir=str(tmp_path / "out"))

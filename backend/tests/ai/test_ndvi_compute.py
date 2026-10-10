import re
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

from compute_ndvi import compute  # noqa: E402
from raster_utils import AllPixelsInvalidError, StaleS2CompositeError  # noqa: E402


def _write_tif(path: Path, data: np.ndarray, *, nodata=None, tags=None) -> None:
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
        if data.dtype.kind == "f" and not tags:
            dst.units = ("reflectance",) * len(data)
        if tags:
            dst.update_tags(**tags)


def test_compute_ndvi_writes_raster_preview_and_stats(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.zeros((4, 3, 3), dtype=np.uint16)
    data[2] = np.array(
        [
            [10, 20, 30],
            [10, 20, 30],
            [10, 20, 30],
        ],
        dtype=np.uint16,
    )
    data[3] = np.array(
        [
            [30, 40, 50],
            [30, 40, 50],
            [30, 40, 50],
        ],
        dtype=np.uint16,
    )
    _write_tif(input_path, data)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir), red_band=3, nir_band=4)

    assert (output_dir / stats["output_tif"]).exists()
    assert (output_dir / stats["output_png"]).exists()
    assert re.fullmatch(r"ndvi_[0-9a-f]{16}\.tif", stats["output_tif"])
    assert re.fullmatch(r"ndvi_[0-9a-f]{16}_colored\.png", stats["output_png"])
    assert list(output_dir.glob("ndvi_*_stats.json"))

    with rasterio.open(output_dir / stats["output_tif"]) as src:
        ndvi = src.read(1)

    expected = (data[3].astype(np.float32) - data[2].astype(np.float32)) / (
        data[3].astype(np.float32) + data[2].astype(np.float32)
    )
    np.testing.assert_allclose(ndvi, expected)
    np.testing.assert_allclose(stats["min"], float(np.min(expected)), rtol=1e-4)
    np.testing.assert_allclose(stats["max"], float(np.max(expected)), rtol=1e-4)
    np.testing.assert_allclose(stats["mean"], float(np.mean(expected)), rtol=1e-4)
    np.testing.assert_allclose(stats["std"], float(np.std(expected)), rtol=1e-4)
    assert stats["nodata_pct"] == 0.0
    # GF-2 类无定标 DN：比值类指数照算，但标注 calibrated: false（A5.2）
    assert stats["calibrated"] is False


def test_compute_ndvi_rejects_zero_band_index(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, np.ones((4, 2, 2), dtype=np.uint16))

    with pytest.raises(ValueError, match="1-based positive"):
        compute(input_path=str(input_path), output_dir=str(output_dir), red_band=0, nir_band=4)


def test_compute_ndvi_handles_zero_denominator_as_nodata(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.zeros((4, 2, 2), dtype=np.uint16)
    data[2] = np.array([[0, 10], [0, 20]], dtype=np.uint16)
    data[3] = np.array([[0, 30], [0, 40]], dtype=np.uint16)
    _write_tif(input_path, data)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir), red_band=3, nir_band=4)
    with rasterio.open(output_dir / stats["output_tif"]) as src:
        ndvi = src.read(1)

    assert np.isnan(ndvi[0, 0])
    assert np.isnan(ndvi[1, 0])
    np.testing.assert_allclose(ndvi[0, 1], 0.5, rtol=1e-4)
    np.testing.assert_allclose(ndvi[1, 1], 1 / 3, rtol=1e-4)
    assert stats["nodata_pct"] == 50.0


def test_compute_ndvi_rejects_band_index_above_available_count(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, np.ones((4, 2, 2), dtype=np.uint16))

    with pytest.raises(ValueError, match="exceed available bands"):
        compute(input_path=str(input_path), output_dir=str(output_dir), red_band=3, nir_band=5)


def test_compute_ndvi_all_nodata_raises_explicit_error(tmp_path: Path) -> None:
    """全部无效的影像返回明确错误，不得静默输出 0 统计（A3 验收）。

    断言修改说明：旧测试断言 min/max/mean/std=0 且 nodata_pct=100，把
    "全无效返回 0 统计"固化成了规格；工作单 A3 要求改为明确错误。
    """
    input_path = tmp_path / "input.tif"
    data = np.zeros((4, 2, 2), dtype=np.uint16)
    _write_tif(input_path, data)

    with pytest.raises(AllPixelsInvalidError, match="all_pixels_invalid"):
        compute(input_path=str(input_path), output_dir=str(tmp_path / "out"), red_band=3, nir_band=4)


def test_compute_ndvi_calibrated_flag_for_reflectance_input(tmp_path: Path) -> None:
    """float 反射率输入：calibrated=True（反射率域直接使用）。"""
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    red = np.full((2, 2), 0.1, dtype=np.float32)
    nir = np.full((2, 2), 0.3, dtype=np.float32)
    _write_tif(input_path, np.stack([red, red, red, nir]).astype(np.float32))

    stats = compute(input_path=str(input_path), output_dir=str(output_dir), red_band=3, nir_band=4)

    # 手算：NDVI = (0.3-0.1)/(0.3+0.1) = 0.5
    np.testing.assert_allclose(stats["mean"], 0.5, rtol=1e-4)
    assert stats["calibrated"] is True


# ---------- A6：输出文件名带 uuid 后缀，重跑不覆盖 ----------


def test_compute_ndvi_rerun_keeps_previous_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.stack([
        np.full((2, 2), 100, dtype=np.uint16),
        np.full((2, 2), 100, dtype=np.uint16),
        np.full((2, 2), 1000, dtype=np.uint16),
        np.full((2, 2), 3000, dtype=np.uint16),
    ])
    _write_tif(input_path, data)

    first = compute(input_path=str(input_path), output_dir=str(output_dir))
    first_tif = output_dir / first["output_tif"]
    first_bytes = first_tif.read_bytes()
    second = compute(input_path=str(input_path), output_dir=str(output_dir))

    assert first["output_tif"] != second["output_tif"]
    assert first_tif.exists() and (output_dir / second["output_tif"]).exists()
    assert first_tif.read_bytes() == first_bytes  # 第一次的文件内容不变


# ---------- D3（2026-10-07）：S2 L2A BOA offset 标签路径 ----------
# PB>=04.00 的 L2A：ρ=(DN-1000)/10000（SentiWiki 产品定义；c1-l2a 条目
# raster:bands {scale 0.0001, offset -0.1} 一致）。compose 写 REFL_* 标签，
# compute_ndvi 的定标必须应用。真实场景实测：漏偏置 NDVI 均值 0.211 vs
# 参考 0.327、RMSE 0.175（docs/test-remediation-plan-2026-10-07.md D3）。


def test_compute_ndvi_applies_s2_boa_offset_tags(tmp_path: Path) -> None:
    """手算：nir DN=4000、red DN=2000 → ρ=0.30/0.10 → NDVI=0.20/0.40=0.5。

    同 DN 显式声明 offset=0 的对照得到 2000/6000=1/3；
    偏置会改变比值类指数。任何成像日期都不能替代定标参数。
    """
    data = np.stack([
        np.full((2, 2), 1800, dtype=np.uint16),  # blue
        np.full((2, 2), 1900, dtype=np.uint16),  # green
        np.full((2, 2), 2000, dtype=np.uint16),  # red
        np.full((2, 2), 4000, dtype=np.uint16),  # nir
    ])
    tagged = tmp_path / "tagged.tif"
    _write_tif(tagged, data, tags={"SENSOR": "Sentinel-2C", "REFL_SCALE": "0.0001", "REFL_OFFSET": "-0.1"})
    stats = compute(input_path=str(tagged), output_dir=str(tmp_path / "o1"), red_band=3, nir_band=4)
    np.testing.assert_allclose(stats["mean"], 0.5, rtol=1e-4)
    assert stats["calibrated"] is True

    zero_offset = tmp_path / "zero_offset.tif"
    _write_tif(zero_offset, data,
               tags={"SENSOR": "Sentinel-2C", "ACQUISITIONDATE": "2021-06-01T10:00:00Z", "REFL_SCALE": ".0001", "REFL_OFFSET": "0"})
    stats_zero_offset = compute(input_path=str(zero_offset), output_dir=str(tmp_path / "o2"), red_band=3, nir_band=4)
    np.testing.assert_allclose(stats_zero_offset["mean"], 1.0 / 3.0, rtol=1e-4)


# ---------- 定标兜底：修复前合成的旧 S2 缓存拒绝计算（D3 收尾） ----------
# NDVI 是实测受影响最重的指数（D3 真实场景：旧路径均值 0.211 vs 参考 0.327，
# 此为单景记录，不是固定误差）。缺失定标标签的 S2 → StaleS2CompositeError，
# 不允许"未定标照算"的静默分支把错误数字发出去。


def test_compute_ndvi_rejects_stale_s2_composite(tmp_path: Path) -> None:
    data = np.stack([
        np.full((2, 2), 1800, dtype=np.uint16),
        np.full((2, 2), 1900, dtype=np.uint16),
        np.full((2, 2), 2000, dtype=np.uint16),
        np.full((2, 2), 4000, dtype=np.uint16),
    ])
    for name, extra in (
        ("new_date", {"ACQUISITIONDATE": "2024-06-01T10:30:00Z"}),
        ("no_date", {}),
    ):
        inp = tmp_path / f"stale_{name}.tif"
        _write_tif(inp, data, tags={"SENSOR": "Sentinel-2C", **extra})
        with pytest.raises(StaleS2CompositeError, match="stale_s2_composite"):
            compute(input_path=str(inp), output_dir=str(tmp_path / name), red_band=3, nir_band=4)

"""A3：统一 valid_mask —— 5 种 nodata 约定 × 4 个指数/掩膜工具。

历史 bug：各 compute 各写一套 `band == nodata` 判断，NaN 型 nodata 永不相等：
NaN 进入云掩膜分位计算使阈值变 NaN（Landsat 场景几乎总报 0% 云）；
water 把 NaN 像元记成"非水体"；compute_ndvi 完全没有 nodata 处理，
-9999 填充值以有限垃圾值污染 min/mean/std。
修复后四个工具统一走 raster_utils.valid_mask（工作单 A3）。

期望值全部独立手算：
- 有效像元恒为 red=0.10 / nir=0.30（DN 1000/3000），NDVI=(0.3-0.1)/0.4=0.5；
  green=0.06 / nir=0.30 -> NDWI=(0.06-0.30)/0.36=-2/3（非水体）。
- 每景 2x2，其中 1 个像元（25%）为 nodata 填充值。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

from compute_cloud_mask import NODATA as CLOUD_NODATA  # noqa: E402
from compute_cloud_mask import compute as compute_cloud  # noqa: E402
from compute_ndvi import compute as compute_ndvi  # noqa: E402
from compute_spectral_index import compute as compute_spectral  # noqa: E402
from compute_water_mask import NODATA as WATER_NODATA  # noqa: E402
from compute_water_mask import compute as compute_water  # noqa: E402
from raster_utils import AllPixelsInvalidError  # noqa: E402

# (用例名, nodata 元数据值, dtype, 是否需要 S2 标签让整型 DN 可定标)
NODATA_CASES = [
    ("zero_uint16", 0, "uint16", True),
    ("fill_-9999_float", -9999.0, "float32", False),
    ("fill_65535_uint16", 65535, "uint16", True),
    ("nan_float", float("nan"), "float32", False),
    ("none_meta_with_nan_pixels", None, "float32", False),
]

# 反射率域的像元取值（float 用）；uint16 用 DN = 反射率 * 10000（S2 约定）。
RED, NIR, GREEN = 0.10, 0.30, 0.06


def _make_bands(dtype: str) -> dict[str, np.ndarray]:
    scale = 10000.0 if dtype == "uint16" else 1.0  # uint16 用 S2 约定 DN = 反射率*10000

    def const(value: float) -> np.ndarray:
        arr = np.full((2, 2), value * scale, dtype=np.float32)
        return arr if dtype == "float32" else arr.astype(dtype)

    return {"blue": const(0.08), "green": const(GREEN), "red": const(RED), "nir": const(NIR)}


def _fill_value(case_dtype: str, nodata) -> float:
    if nodata is None:
        return float("nan")
    if case_dtype == "uint16":
        return float(nodata)
    return float(nodata)


@pytest.mark.parametrize(("case_name", "nodata", "dtype", "need_s2_tag"), NODATA_CASES)
def test_ndvi_nodata_pct_and_stats_are_correct(tmp_path, case_name, nodata, dtype, need_s2_tag) -> None:
    """nodata ∈ 5 种约定 × ndvi：nodata_pct=25，mean=0.5（不受填充值污染）。"""
    bands = _make_bands(dtype)
    fill = _fill_value(dtype, nodata)
    data = np.stack([bands["blue"], bands["green"], bands["red"], bands["nir"]])
    for band in data:
        band[0, 0] = fill
    inp = tmp_path / "in.tif"
    tags = (
        {"SENSOR": "Sentinel-2B", "REFL_SCALE": ".0001", "REFL_OFFSET": "0"}
        if need_s2_tag else None
    )  # 合成测试明确给出零offset；成像日期不作为定标证据
    with rasterio.open(inp, "w", driver="GTiff", height=2, width=2, count=4,
                       dtype=dtype, nodata=nodata, transform=from_origin(0, 2, 1, 1)) as dst:
        dst.write(data.astype(dtype))
        if dtype == "float32":
            dst.units = ("reflectance",) * data.shape[0]
        if tags:
            dst.update_tags(**tags)

    stats = compute_ndvi(input_path=str(inp), output_dir=str(tmp_path / "out"), red_band=3, nir_band=4)

    # 手算：有效像元 NDVI 恒 = (0.3-0.1)/(0.3+0.1) = 0.5
    assert stats["nodata_pct"] == 25.0
    assert stats["mean"] == pytest.approx(0.5, abs=1e-4)
    assert stats["min"] == pytest.approx(0.5, abs=1e-4)
    assert stats["max"] == pytest.approx(0.5, abs=1e-4)
    assert stats["std"] == pytest.approx(0.0, abs=1e-4)


@pytest.mark.parametrize(("case_name", "nodata", "dtype", "need_s2_tag"), NODATA_CASES)
def test_spectral_index_nodata_pct_and_stats_are_correct(
    tmp_path, case_name, nodata, dtype, need_s2_tag
) -> None:
    """nodata ∈ 5 种约定 × spectral_index(ndwi)：nodata_pct=25，mean 手算 -2/3。"""
    bands = _make_bands(dtype)
    fill = _fill_value(dtype, nodata)
    data = np.stack([bands["blue"], bands["green"], bands["red"], bands["nir"]])
    for band in data:
        band[0, 0] = fill
    inp = tmp_path / "in.tif"
    tags = (
        {"SENSOR": "Sentinel-2B", "REFL_SCALE": ".0001", "REFL_OFFSET": "0"}
        if need_s2_tag else None
    )  # 合成测试明确给出零offset；成像日期不作为定标证据
    with rasterio.open(inp, "w", driver="GTiff", height=2, width=2, count=4,
                       dtype=dtype, nodata=nodata, transform=from_origin(0, 2, 1, 1)) as dst:
        dst.write(data.astype(dtype))
        if dtype == "float32":
            dst.units = ("reflectance",) * data.shape[0]
        if tags:
            dst.update_tags(**tags)

    stats = compute_spectral(input_path=str(inp), output_dir=str(tmp_path / "out"), index_type="ndwi")

    # 手算：有效像元 NDWI = (0.06-0.30)/(0.06+0.30) = -24/36 = -2/3
    assert stats["nodata_pct"] == 25.0
    assert stats["mean"] == pytest.approx(-2.0 / 3.0, abs=1e-4)


@pytest.mark.parametrize(("case_name", "nodata", "dtype", "need_s2_tag"), NODATA_CASES)
def test_water_mask_nodata_pct_is_correct(tmp_path, case_name, nodata, dtype, need_s2_tag) -> None:
    """nodata ∈ 5 种约定 × water_mask：nodata_pct=25，其余像元 NDWI=-2/3 非水体。"""
    bands = _make_bands(dtype)
    fill = _fill_value(dtype, nodata)
    data = np.stack([bands["blue"], bands["green"], bands["red"], bands["nir"]])
    for band in data:
        band[0, 0] = fill
    inp = tmp_path / "in.tif"
    tags = (
        {"SENSOR": "Sentinel-2B", "REFL_SCALE": ".0001", "REFL_OFFSET": "0"}
        if need_s2_tag else None
    )  # 合成测试明确给出零offset；成像日期不作为定标证据
    with rasterio.open(inp, "w", driver="GTiff", height=2, width=2, count=4,
                       dtype=dtype, nodata=nodata, transform=from_origin(0, 2, 1, 1)) as dst:
        dst.write(data.astype(dtype))
        if dtype == "float32":
            dst.units = ("reflectance",) * data.shape[0]
        if tags:
            dst.update_tags(**tags)

    stats = compute_water(input_path=str(inp), output_dir=str(tmp_path / "out"))

    assert stats["nodata_pct"] == 25.0
    assert stats["non_water_pct"] == 75.0
    assert stats["water_pct"] == 0.0


@pytest.mark.parametrize(("case_name", "nodata", "dtype", "need_s2_tag"), NODATA_CASES)
def test_cloud_mask_nodata_pct_is_correct(tmp_path, case_name, nodata, dtype, need_s2_tag) -> None:
    """nodata ∈ 5 种约定 × cloud_mask：nodata_pct=25，其余像元全晴空。

    回归锁定：NaN nodata 时 `band == nodata` 永假，NaN 进入分位计算使阈值
    变 NaN -> 整景报 0% 云（工作单 A3 的 Landsat 场景 bug）。
    """
    bands = _make_bands(dtype)
    fill = _fill_value(dtype, nodata)
    data = np.stack([bands["blue"], bands["green"], bands["red"], bands["nir"]])
    for band in data:
        band[0, 0] = fill
    inp = tmp_path / "in.tif"
    tags = (
        {"SENSOR": "Sentinel-2B", "REFL_SCALE": ".0001", "REFL_OFFSET": "0"}
        if need_s2_tag else None
    )  # 合成测试明确给出零offset；成像日期不作为定标证据
    with rasterio.open(inp, "w", driver="GTiff", height=2, width=2, count=4,
                       dtype=dtype, nodata=nodata, transform=from_origin(0, 2, 1, 1)) as dst:
        dst.write(data.astype(dtype))
        if dtype == "float32":
            dst.units = ("reflectance",) * data.shape[0]
        if tags:
            dst.update_tags(**tags)

    stats = compute_cloud(method="heuristic", input_path=str(inp), output_dir=str(tmp_path / "out"))

    assert stats["nodata_pct"] == 25.0
    assert stats["candidate_other_pct"] == 75.0
    assert stats["candidate_bright_pct"] == 0.0
    assert stats["candidate_dark_pct"] == 0.0


def test_tools_handle_sparse_nan_edge(tmp_path: Path) -> None:
    """边缘：5% NaN 的影像（20x20=400 像元，20 个 NaN）。"""
    h = w = 20
    red = np.full((h, w), RED, dtype=np.float32)
    nir = np.full((h, w), NIR, dtype=np.float32)
    nan_positions = [(i, j) for i in range(h) for j in range(w)][:20]
    for i, j in nan_positions:
        red[i, j] = np.nan
        nir[i, j] = np.nan
    inp = tmp_path / "in.tif"
    with rasterio.open(inp, "w", driver="GTiff", height=h, width=w, count=4,
                       dtype="float32", nodata=float("nan"), transform=from_origin(0, h, 1, 1)) as dst:
        dst.write(np.stack([red, red, red, nir]).astype(np.float32))
        dst.units = ("reflectance",) * 4

    stats = compute_ndvi(input_path=str(inp), output_dir=str(tmp_path / "o1"), red_band=3, nir_band=4)
    assert stats["nodata_pct"] == 5.0  # 20/400
    assert stats["mean"] == pytest.approx(0.5, abs=1e-4)

    cloud_stats = compute_cloud(method="heuristic", input_path=str(inp), output_dir=str(tmp_path / "o2"))
    assert cloud_stats["nodata_pct"] == 5.0
    assert cloud_stats["candidate_bright_pct"] == 0.0


@pytest.mark.parametrize(
    "runner",
    [
        lambda inp, out: compute_ndvi(input_path=inp, output_dir=out, red_band=3, nir_band=4),
        lambda inp, out: compute_spectral(input_path=inp, output_dir=out, index_type="ndwi"),
        lambda inp, out: compute_water(input_path=inp, output_dir=out),
        lambda inp, out: compute_cloud(method="heuristic", input_path=inp, output_dir=out),
    ],
    ids=["ndvi", "spectral_index", "water_mask", "cloud_mask"],
)
def test_all_invalid_image_raises_explicit_error(tmp_path: Path, runner) -> None:
    """异常：全部无效的影像返回明确错误，不得输出 0% / 0 统计（A3 验收）。"""
    inp = tmp_path / "all_nan.tif"
    with rasterio.open(inp, "w", driver="GTiff", height=2, width=2, count=4,
                       dtype="float32", nodata=float("nan"), transform=from_origin(0, 2, 1, 1)) as dst:
        dst.write(np.full((4, 2, 2), np.nan, dtype=np.float32))

    with pytest.raises(AllPixelsInvalidError, match="all_pixels_invalid"):
        runner(str(inp), str(tmp_path / "out"))


def test_valid_mask_unit_semantics(tmp_path: Path) -> None:
    """valid_mask 单元语义：NaN/有限 nodata/整型全 0 三类无效来源叠加。"""
    import raster_utils  # noqa: E402

    inp = tmp_path / "m.tif"
    red = np.array([[RED, np.nan], [-9999.0, RED]], dtype=np.float32)
    nir = np.array([[NIR, np.nan], [NIR, NIR]], dtype=np.float32)
    with rasterio.open(inp, "w", driver="GTiff", height=2, width=2, count=2,
                       dtype="float32", nodata=-9999.0, transform=from_origin(0, 2, 1, 1)) as dst:
        dst.write(np.stack([red, nir]))

    with rasterio.open(inp) as src:
        r, n = src.read(1).astype(np.float32), src.read(2).astype(np.float32)
        mask = raster_utils.valid_mask(src, (r, n))

    # [0,0] 有效；[0,1] NaN 无效；[1,0] nodata=-9999 无效；[1,1] 有效。
    assert mask.tolist() == [[True, False], [False, True]]

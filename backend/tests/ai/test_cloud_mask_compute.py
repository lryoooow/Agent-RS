"""Explicit historical bright/dark baseline: rule execution tests, not cloud accuracy validation."""
import re
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

from compute_cloud_mask import CLEAR, CLOUD, NODATA, SHADOW, compute  # noqa: E402
from raster_utils import StaleS2CompositeError, UncalibratedInputError  # noqa: E402


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
        if str(data.dtype).startswith("float"):
            dst.units = ("reflectance",) * data.shape[0]
        if tags:
            dst.update_tags(**tags)


def _reflectance_scene(cloud_frac: float, size: int = 10, seed: int = 3):
    """构造反射率影像（float32，值域 0-1 -> compute 视为 already_reflectance）。

    云像元是"白色"的：同一基础亮度（U(0.5,0.9)）加微小波段间抖动，
    NDVI/NDWI 接近 0；植被像元可见光暗（U(0.05,0.15)）、NIR 高（U(0.3,0.5)），
    NDVI ~ 0.5。云像元占展平后前 cloud_frac*size*size 个位置，占比精确可控。
    """
    rng = np.random.default_rng(seed)
    total = size * size
    nc = round(cloud_frac * total)
    base = rng.uniform(0.5, 0.9, nc)
    vis_c = base + rng.uniform(-0.02, 0.02, nc)
    nir_c = base + rng.uniform(-0.02, 0.02, nc)
    vis_g = rng.uniform(0.05, 0.15, total - nc)
    nir_g = rng.uniform(0.3, 0.5, total - nc)
    vis = np.concatenate([vis_c, vis_g]).reshape(size, size).astype(np.float32)
    nir = np.concatenate([nir_c, nir_g]).reshape(size, size).astype(np.float32)
    return np.stack([vis, vis, vis, nir]).astype(np.float32)


def test_compute_cloud_mask_writes_outputs_and_stats(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    # 4 波段反射率：顶行云（白、亮）、底行阴影（暗、非水）、中间植被。
    h, w = 4, 4
    vis = np.full((h, w), 0.10, dtype=np.float32)  # 植被：可见光暗
    nir = np.full((h, w), 0.40, dtype=np.float32)  # 植被：NIR 高

    vis[0, :] = 0.70  # 云：白且亮（VIS 均值 0.70 > 0.3），NDVI/NDWI ~ 0
    nir[0, :] = 0.68
    vis[-1, :] = 0.02  # 阴影：全波段暗，NDWI=(0.02-0.03)/0.05<0（非水体）
    nir[-1, :] = 0.03

    _write_tif(input_path, np.stack([vis, vis, vis, nir]))

    stats = compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir))

    assert (output_dir / stats["output_tif"]).exists()
    assert (output_dir / stats["output_png"]).exists()
    assert re.fullmatch(r"cloud_mask_[0-9a-f]{16}\.tif", stats["output_tif"])
    assert list(output_dir.glob("cloud_mask_*_stats.json"))

    total_pct = stats["candidate_bright_pct"] + stats["candidate_dark_pct"] + stats["candidate_other_pct"] + stats["nodata_pct"]
    assert abs(total_pct - 100.0) < 0.5

    with rasterio.open(output_dir / stats["output_tif"]) as src:
        classification = src.read(1)
        assert src.dtypes[0] == "uint8"

    assert np.all(classification[0, :] == CLOUD)
    assert np.all(classification[-1, :] == SHADOW)
    assert np.all(classification[1:-1, :] == CLEAR)
    assert set(np.unique(classification)).issubset({CLEAR, CLOUD, SHADOW, NODATA})
    assert stats["cloud_pct"] is None and stats["shadow_pct"] is None and stats["clear_pct"] is None
    assert stats["method"] == "heuristic" and stats["method_validation"] == "unvalidated"
    # 仅验证旧基线执行，候选比例并非实际云量。
    assert stats["threshold_method"] == "absolute_reflectance_candidates"
    assert stats["cloud_vis_threshold"] == 0.3
    assert stats["shadow_nir_threshold"] == 0.1
    assert stats["calibration"] == "already_reflectance"


# ---------- A2：反射率绝对阈值（未验证的亮暗候选规则），分位封顶修复 ----------


@pytest.mark.parametrize(
    ("cloud_frac", "expected_pct", "tolerance"),
    [
        (1.00, 100.0, 5.0),  # 全云：报 >= 95%
        (0.70, 70.0, 2.0),   # 70% 云：误差 <= 2 个百分点
    ],
)
def test_explicit_baseline_reports_bright_candidate_fraction(
    tmp_path: Path, cloud_frac: float, expected_pct: float, tolerance: float
) -> None:
    """正常/回归：全云与 70% 云。回归锁定（历史 bug：亮度 80 分位阈值把云
    占比封顶在 ~20%，全云影像只报 20%——2026-10-07 工作单 A2）。"""
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, _reflectance_scene(cloud_frac))

    stats = compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir))

    assert abs(stats["candidate_bright_pct"] - expected_pct) <= tolerance
    assert stats["candidate_dark_pct"] <= 1.0


def test_explicit_baseline_unflagged_scene_has_no_dark_candidates(tmp_path: Path) -> None:
    """正常：晴空无阴影影像 shadow_pct <= 1%（回归：历史 bug 用 NIR 20 分位
    当暗阈值，晴空植被影像凭空报出 ~20% 阴影——工作单 A2）。"""
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, _reflectance_scene(0.0))

    stats = compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir))

    assert stats["candidate_dark_pct"] <= 1.0
    assert stats["candidate_bright_pct"] == 0.0


def test_explicit_baseline_dark_scene(tmp_path: Path) -> None:
    """正常：仅阴影。暗像元（NIR=0.03 < 0.1）且非水体 -> 全部判为阴影。"""
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    vis = np.full((4, 4), 0.02, dtype=np.float32)
    nir = np.full((4, 4), 0.03, dtype=np.float32)
    _write_tif(input_path, np.stack([vis, vis, vis, nir]))

    stats = compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir))

    assert stats["candidate_dark_pct"] == 100.0


def test_explicit_baseline_water_is_not_dark_candidate(tmp_path: Path) -> None:
    """正常：云+水混合。水体（green=0.05, nir=0.01 -> NDWI=2/3>0）NIR 虽暗
    但不得被判为阴影（工作单 A2：水不应被判为阴影）。"""
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    vis = np.hstack([np.full((2, 2), 0.70, dtype=np.float32), np.full((2, 2), 0.05, dtype=np.float32)])
    nir = np.hstack([np.full((2, 2), 0.68, dtype=np.float32), np.full((2, 2), 0.01, dtype=np.float32)])
    _write_tif(input_path, np.stack([vis, vis, vis, nir]))

    stats = compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir))

    assert stats["candidate_dark_pct"] == 0.0
    assert stats["candidate_bright_pct"] == 50.0
    with rasterio.open(output_dir / stats["output_tif"]) as src:
        classification = src.read(1)
    assert np.all(classification[:, 2:] == CLEAR)  # 水体像元=晴空类别


def test_compute_cloud_mask_sentinel2_dn_is_calibrated(tmp_path: Path) -> None:
    """正常：带 SENSOR 标签的 S2 uint16 DN 先定标（DN/10000）再判。

    手算：DN 6000 -> 0.60 > 0.3（云）；DN 1200 -> 0.12（植被，NDVI 高）。
    日期取 2022-01-25 前（offset 确为 0）——新日期的无标签 S2 由
    stale_s2_composite 兜底拒绝（见下一条用例）。
    """
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    vis = np.full((2, 2), 1200, dtype=np.uint16)
    nir = np.full((2, 2), 4000, dtype=np.uint16)
    vis[:, 0] = 6000
    nir[:, 0] = 5800
    _write_tif(input_path, np.stack([vis, vis, vis, nir]),
               tags={"SENSOR": "Sentinel-2B", "REFL_SCALE": "0.0001", "REFL_OFFSET": "0", "REFL_QUANTITY": "surface_reflectance"})

    stats = compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir))

    assert stats["calibration"] == "declared_reflectance"
    assert stats["candidate_bright_pct"] == 50.0


def test_compute_cloud_mask_rejects_stale_s2_composite(tmp_path: Path) -> None:
    """定标兜底（D3 收尾）：无 REFL_* 标签 + 成像 >= 2022-01-25 的 S2 旧缓存
    → StaleS2CompositeError，云掩膜的绝对反射率阈值同样会被错定标污染。"""
    input_path = tmp_path / "stale.tif"
    vis = np.full((2, 2), 1200, dtype=np.uint16)
    nir = np.full((2, 2), 4000, dtype=np.uint16)
    _write_tif(input_path, np.stack([vis, vis, vis, nir]),
               tags={"SENSOR": "Sentinel-2B", "ACQUISITIONDATE": "2024-06-01T10:30:00Z"})

    with pytest.raises(StaleS2CompositeError, match="stale_s2_composite"):
        compute(method="heuristic", input_path=str(input_path), output_dir=str(tmp_path / "output"))


def test_compute_cloud_mask_rejects_uncalibrated_input(tmp_path: Path) -> None:
    """异常：无定标信息（GF-2 上传 DN，无传感器标签）-> uncalibrated_input，
    不允许静默按 DN 计算（工作单 A2）。"""
    input_path = tmp_path / "input.tif"
    data = np.full((4, 2, 2), 900, dtype=np.uint16)
    _write_tif(input_path, data)

    with pytest.raises(UncalibratedInputError, match="uncalibrated_input"):
        compute(method="heuristic", input_path=str(input_path), output_dir=str(tmp_path / "output"))


def test_compute_cloud_mask_marks_nodata(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.full((4, 2, 2), 0.2, dtype=np.float32)
    data[:, 0, 0] = 0.0  # 一个像素四波段为 nodata=0
    _write_tif(input_path, data, nodata=0.0)

    stats = compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir))

    with rasterio.open(output_dir / stats["output_tif"]) as src:
        classification = src.read(1)

    assert classification[0, 0] == NODATA
    assert stats["nodata_pct"] == 25.0


# ---------- A6：输出文件名带 uuid 后缀，重跑不覆盖 ----------


def test_compute_cloud_mask_rerun_keeps_previous_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, _reflectance_scene(0.5))

    first = compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir))
    first_tif = output_dir / first["output_tif"]
    first_bytes = first_tif.read_bytes()
    second = compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir))

    assert first["output_tif"] != second["output_tif"]
    assert first_tif.exists() and (output_dir / second["output_tif"]).exists()
    assert first_tif.read_bytes() == first_bytes


# ---------- 原有参数校验 ----------


def test_compute_cloud_mask_rejects_band_above_count(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, np.ones((4, 2, 2), dtype=np.uint16))

    with pytest.raises(ValueError, match="but imagery has"):
        compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir), nir_band=5)


def test_compute_cloud_mask_rejects_zero_band(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, np.ones((4, 2, 2), dtype=np.uint16))

    with pytest.raises(ValueError, match="must be >= 1"):
        compute(method="heuristic", input_path=str(input_path), output_dir=str(output_dir), red_band=0)


def test_compute_cloud_mask_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compute(method="heuristic", input_path=str(tmp_path / "nope.tif"), output_dir=str(tmp_path / "out"))

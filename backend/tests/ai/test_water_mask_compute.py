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

    assert (output_dir / "water_mask.tif").exists()
    assert (output_dir / "water_mask_colored.png").exists()
    assert (output_dir / "water_mask_stats.json").exists()
    assert stats["output_tif"] == "water_mask.tif"
    assert stats["output_png"] == "water_mask_colored.png"

    total_pct = stats["water_pct"] + stats["non_water_pct"] + stats["nodata_pct"]
    assert abs(total_pct - 100.0) < 0.5

    with rasterio.open(output_dir / "water_mask.tif") as src:
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
    with rasterio.open(output_dir / "water_mask.tif") as src:
        classification = src.read(1)
    assert not np.any(classification == WATER)


def test_compute_water_mask_marks_nodata(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.full((4, 2, 2), 200, dtype=np.uint16)
    data[:, 0, 0] = 0  # 一个像素 green/nir 为 0 -> nodata
    _write_tif(input_path, data, nodata=0)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    with rasterio.open(output_dir / "water_mask.tif") as src:
        classification = src.read(1)

    assert classification[0, 0] == NODATA
    assert stats["nodata_pct"] == 25.0


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

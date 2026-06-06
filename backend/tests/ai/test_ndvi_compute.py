import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

from compute_ndvi import compute  # noqa: E402


def _write_tif(path: Path, data: np.ndarray) -> None:
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=data.shape[1],
        width=data.shape[2],
        count=data.shape[0],
        dtype=str(data.dtype),
        transform=from_origin(0, data.shape[1], 1, 1),
    ) as dst:
        dst.write(data)


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

    assert (output_dir / "ndvi.tif").exists()
    assert (output_dir / "ndvi_colored.png").exists()
    assert (output_dir / "ndvi_stats.json").exists()
    assert stats["output_tif"] == "ndvi.tif"
    assert stats["output_png"] == "ndvi_colored.png"

    with rasterio.open(output_dir / "ndvi.tif") as src:
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
    with rasterio.open(output_dir / "ndvi.tif") as src:
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


def test_compute_ndvi_all_nodata_returns_fallback_stats(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.zeros((4, 2, 2), dtype=np.uint16)
    _write_tif(input_path, data)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir), red_band=3, nir_band=4)

    assert stats["min"] == 0.0
    assert stats["max"] == 0.0
    assert stats["mean"] == 0.0
    assert stats["std"] == 0.0
    assert stats["nodata_pct"] == 100.0

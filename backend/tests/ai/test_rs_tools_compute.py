from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

from compute_band_composite import render  # noqa: E402
from compute_raster_inspect import inspect  # noqa: E402
from compute_spectral_index import compute  # noqa: E402


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


def test_raster_inspect_reports_band_capabilities(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    data = np.ones((4, 2, 2), dtype=np.uint16)
    _write_tif(input_path, data)

    result = inspect(str(input_path))

    assert result["band_count"] == 4
    assert result["capabilities"]["has_nir"] is True
    assert result["capabilities"]["has_swir"] is False
    assert len(result["per_band_stats"]) == 4


def test_spectral_index_ndwi_matches_ground_truth(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.zeros((4, 2, 2), dtype=np.uint16)
    data[1] = np.array([[30, 40], [50, 60]], dtype=np.uint16)
    data[3] = np.array([[10, 20], [30, 40]], dtype=np.uint16)
    _write_tif(input_path, data)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir), index_type="ndwi")

    expected = (data[1].astype(np.float32) - data[3].astype(np.float32)) / (
        data[1].astype(np.float32) + data[3].astype(np.float32)
    )
    with rasterio.open(output_dir / "ndwi.tif") as src:
        actual = src.read(1)
    np.testing.assert_allclose(actual, expected, rtol=1e-4)
    np.testing.assert_allclose(stats["mean"], float(np.mean(expected)), rtol=1e-4)
    assert (output_dir / "ndwi_colored.png").exists()


def test_spectral_index_requires_swir_for_ndbi(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    data = np.ones((4, 2, 2), dtype=np.uint16)
    _write_tif(input_path, data)

    with pytest.raises(ValueError, match="requires swir_band"):
        compute(input_path=str(input_path), output_dir=str(tmp_path / "output"), index_type="ndbi")


def test_spectral_index_zero_denominator_has_no_nan_stats(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    data = np.zeros((4, 2, 2), dtype=np.uint16)
    _write_tif(input_path, data)

    stats = compute(input_path=str(input_path), output_dir=str(tmp_path / "output"), index_type="ndwi")

    assert stats["min"] == 0.0
    assert stats["max"] == 0.0
    assert stats["mean"] == 0.0
    assert stats["nodata_pct"] == 100.0


def test_band_composite_writes_png(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.stack(
        [
            np.full((3, 3), 10, dtype=np.uint16),
            np.full((3, 3), 20, dtype=np.uint16),
            np.full((3, 3), 30, dtype=np.uint16),
            np.full((3, 3), 40, dtype=np.uint16),
        ]
    )
    _write_tif(input_path, data)

    result = render(input_path=str(input_path), output_dir=str(output_dir), mode="false_color")

    assert result["bands_used"] == [4, 3, 2]
    assert (output_dir / "composite_false_color.png").exists()

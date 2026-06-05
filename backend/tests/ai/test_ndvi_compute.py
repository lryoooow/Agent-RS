import os
import subprocess
import sys
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin


def test_compute_ndvi_script_writes_raster_preview_and_stats(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    script_path = Path(__file__).resolve().parents[3] / "docker" / "ndvi" / "compute_ndvi.py"

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

    with rasterio.open(
        input_path,
        "w",
        driver="GTiff",
        height=3,
        width=3,
        count=4,
        dtype="uint16",
        transform=from_origin(0, 3, 1, 1),
    ) as dst:
        dst.write(data)

    env = {
        **os.environ,
        "INPUT_PATH": str(input_path),
        "OUTPUT_DIR": str(output_dir),
        "RED_BAND": "3",
        "NIR_BAND": "4",
    }
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        env=env,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert (output_dir / "ndvi.tif").exists()
    assert (output_dir / "ndvi_colored.png").exists()
    assert (output_dir / "stats.json").exists()

    with rasterio.open(output_dir / "ndvi.tif") as src:
        ndvi = src.read(1)
    stats = json.loads((output_dir / "stats.json").read_text(encoding="utf-8"))

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
    script_path = Path(__file__).resolve().parents[3] / "docker" / "ndvi" / "compute_ndvi.py"

    data = np.ones((4, 2, 2), dtype=np.uint16)
    with rasterio.open(
        input_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=4,
        dtype="uint16",
        transform=from_origin(0, 2, 1, 1),
    ) as dst:
        dst.write(data)

    env = {
        **os.environ,
        "INPUT_PATH": str(input_path),
        "OUTPUT_DIR": str(output_dir),
        "RED_BAND": "0",
        "NIR_BAND": "4",
    }
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        env=env,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    assert "1-based positive" in result.stderr


def test_compute_ndvi_handles_zero_denominator_as_nodata(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    script_path = Path(__file__).resolve().parents[3] / "docker" / "ndvi" / "compute_ndvi.py"

    data = np.zeros((4, 2, 2), dtype=np.uint16)
    data[2] = np.array([[0, 10], [0, 20]], dtype=np.uint16)
    data[3] = np.array([[0, 30], [0, 40]], dtype=np.uint16)
    with rasterio.open(
        input_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=4,
        dtype="uint16",
        transform=from_origin(0, 2, 1, 1),
    ) as dst:
        dst.write(data)

    env = {
        **os.environ,
        "INPUT_PATH": str(input_path),
        "OUTPUT_DIR": str(output_dir),
        "RED_BAND": "3",
        "NIR_BAND": "4",
    }
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        env=env,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    stats = json.loads((output_dir / "stats.json").read_text(encoding="utf-8"))
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
    script_path = Path(__file__).resolve().parents[3] / "docker" / "ndvi" / "compute_ndvi.py"

    data = np.ones((4, 2, 2), dtype=np.uint16)
    with rasterio.open(
        input_path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=4,
        dtype="uint16",
        transform=from_origin(0, 2, 1, 1),
    ) as dst:
        dst.write(data)

    env = {
        **os.environ,
        "INPUT_PATH": str(input_path),
        "OUTPUT_DIR": str(output_dir),
        "RED_BAND": "3",
        "NIR_BAND": "5",
    }
    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        env=env,
        text=True,
        timeout=30,
    )

    assert result.returncode == 1
    assert "exceed available bands" in result.stderr

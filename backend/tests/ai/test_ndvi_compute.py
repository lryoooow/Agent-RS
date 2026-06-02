import os
import subprocess
import sys
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

    expected = (data[3].astype(np.float32) - data[2].astype(np.float32)) / (
        data[3].astype(np.float32) + data[2].astype(np.float32)
    )
    np.testing.assert_allclose(ndvi, expected)

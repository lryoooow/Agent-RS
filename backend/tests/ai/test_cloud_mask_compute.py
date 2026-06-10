import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

from compute_cloud_mask import CLEAR, CLOUD, NODATA, SHADOW, compute  # noqa: E402


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


def test_compute_cloud_mask_writes_outputs_and_stats(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    # 4 波段 (blue,green,red,nir)，构造一片高亮区(云)、一片暗区(阴影)、其余正常植被
    h, w = 4, 4
    blue = np.full((h, w), 100, dtype=np.uint16)
    green = np.full((h, w), 100, dtype=np.uint16)
    red = np.full((h, w), 100, dtype=np.uint16)
    nir = np.full((h, w), 300, dtype=np.uint16)  # 高 NIR -> 正常植被

    # 顶行设为云：可见光极高、NIR 不高于可见光 -> 低 NDVI
    blue[0, :] = green[0, :] = red[0, :] = 900
    nir[0, :] = 900
    # 底行设为阴影：所有波段都很暗（非水体，NDWI 低，NIR 极低）
    blue[-1, :] = green[-1, :] = red[-1, :] = 6
    nir[-1, :] = 5

    data = np.stack([blue, green, red, nir]).astype(np.uint16)
    _write_tif(input_path, data)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    assert (output_dir / "cloud_mask.tif").exists()
    assert (output_dir / "cloud_mask_colored.png").exists()
    assert (output_dir / "cloud_mask_stats.json").exists()
    assert stats["output_tif"] == "cloud_mask.tif"
    assert stats["output_png"] == "cloud_mask_colored.png"

    # 占比之和约等于 100
    total_pct = stats["cloud_pct"] + stats["shadow_pct"] + stats["clear_pct"] + stats["nodata_pct"]
    assert abs(total_pct - 100.0) < 0.5

    with rasterio.open(output_dir / "cloud_mask.tif") as src:
        classification = src.read(1)
        assert src.dtypes[0] == "uint8"

    # 顶行应被判为云，底行应被判为阴影
    assert np.all(classification[0, :] == CLOUD)
    assert np.all(classification[-1, :] == SHADOW)
    # 输出只含合法编码
    assert set(np.unique(classification)).issubset({CLEAR, CLOUD, SHADOW, NODATA})


def test_compute_cloud_mask_marks_nodata(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    data = np.full((4, 2, 2), 200, dtype=np.uint16)
    data[:, 0, 0] = 0  # 一个像素四波段全 0 -> nodata
    _write_tif(input_path, data, nodata=0)

    stats = compute(input_path=str(input_path), output_dir=str(output_dir))

    with rasterio.open(output_dir / "cloud_mask.tif") as src:
        classification = src.read(1)

    assert classification[0, 0] == NODATA
    assert stats["nodata_pct"] == 25.0


def test_compute_cloud_mask_rejects_band_above_count(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, np.ones((4, 2, 2), dtype=np.uint16))

    with pytest.raises(ValueError, match="but imagery has"):
        compute(input_path=str(input_path), output_dir=str(output_dir), nir_band=5)


def test_compute_cloud_mask_rejects_zero_band(tmp_path: Path) -> None:
    input_path = tmp_path / "input.tif"
    output_dir = tmp_path / "output"
    _write_tif(input_path, np.ones((4, 2, 2), dtype=np.uint16))

    with pytest.raises(ValueError, match="must be >= 1"):
        compute(input_path=str(input_path), output_dir=str(output_dir), red_band=0)


def test_compute_cloud_mask_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compute(input_path=str(tmp_path / "nope.tif"), output_dir=str(tmp_path / "out"))

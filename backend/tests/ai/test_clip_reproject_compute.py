import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

RS_TOOLS_DIR = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
sys.path.insert(0, str(RS_TOOLS_DIR))

from compute_clip_reproject import compute  # noqa: E402


def _write_geotiff(path: Path, *, crs: str = "EPSG:4326") -> None:
    """写一张带真实 CRS 的 4 波段影像，覆盖经度 [100,104]、纬度 [30,34]。"""
    h = w = 8
    data = (np.arange(4 * h * w).reshape(4, h, w) % 255).astype(np.uint8)
    # 像素 0.5 度，左上角 (100, 34)
    transform = from_origin(100.0, 34.0, 0.5, 0.5)
    with rasterio.open(
        path, "w", driver="GTiff", height=h, width=w, count=4,
        dtype="uint8", crs=crs, transform=transform, nodata=0,
    ) as dst:
        dst.write(data)


def test_compute_reproject_changes_crs(tmp_path: Path) -> None:
    input_path = tmp_path / "in.tif"
    output_dir = tmp_path / "out"
    _write_geotiff(input_path, crs="EPSG:4326")

    stats = compute(input_path=str(input_path), output_dir=str(output_dir), dst_crs="EPSG:3857")

    assert (output_dir / "clip_reproject.tif").exists()
    assert (output_dir / "clip_reproject_colored.png").exists()
    assert (output_dir / "clip_reproject_stats.json").exists()
    assert stats["reprojected"] is True
    assert stats["clipped"] is False
    assert stats["band_count"] == 4

    with rasterio.open(output_dir / "clip_reproject.tif") as src:
        assert src.crs.to_epsg() == 3857
        assert src.count == 4
        assert src.width >= 1 and src.height >= 1


def test_compute_clip_reduces_extent(tmp_path: Path) -> None:
    input_path = tmp_path / "in.tif"
    output_dir = tmp_path / "out"
    _write_geotiff(input_path, crs="EPSG:4326")

    # 裁到中心一小块，保持源坐标系（仅裁剪）
    stats = compute(
        input_path=str(input_path),
        output_dir=str(output_dir),
        bbox=[101.0, 31.0, 103.0, 33.0],
    )

    assert stats["clipped"] is True
    assert stats["reprojected"] is False
    with rasterio.open(output_dir / "clip_reproject.tif") as src:
        # 裁剪后的范围应落在请求 bbox 附近，且小于原始 4x4 度
        assert (src.bounds.right - src.bounds.left) < 4.0
        assert src.crs.to_epsg() == 4326


def test_compute_clip_and_reproject_together(tmp_path: Path) -> None:
    input_path = tmp_path / "in.tif"
    output_dir = tmp_path / "out"
    _write_geotiff(input_path, crs="EPSG:4326")

    stats = compute(
        input_path=str(input_path),
        output_dir=str(output_dir),
        dst_crs="EPSG:3857",
        bbox=[101.0, 31.0, 103.0, 33.0],
    )

    assert stats["clipped"] is True
    assert stats["reprojected"] is True
    assert "bounds_wgs84" in stats and len(stats["bounds_wgs84"]) == 4


def test_compute_requires_crs_or_bbox(tmp_path: Path) -> None:
    input_path = tmp_path / "in.tif"
    _write_geotiff(input_path)
    with pytest.raises(ValueError, match="at least one"):
        compute(input_path=str(input_path), output_dir=str(tmp_path / "out"))


def test_compute_rejects_invalid_crs(tmp_path: Path) -> None:
    input_path = tmp_path / "in.tif"
    _write_geotiff(input_path)
    with pytest.raises(ValueError, match="Invalid CRS"):
        compute(input_path=str(input_path), output_dir=str(tmp_path / "out"), dst_crs="EPSG:999999999")


def test_compute_rejects_bbox_outside_extent(tmp_path: Path) -> None:
    input_path = tmp_path / "in.tif"
    _write_geotiff(input_path, crs="EPSG:4326")
    # bbox 完全在影像范围之外（影像覆盖经度 100-104）
    with pytest.raises(ValueError, match="overlap"):
        compute(
            input_path=str(input_path),
            output_dir=str(tmp_path / "out"),
            bbox=[200.0, 80.0, 201.0, 81.0],
        )


def test_compute_rejects_bad_resampling(tmp_path: Path) -> None:
    input_path = tmp_path / "in.tif"
    _write_geotiff(input_path)
    with pytest.raises(ValueError, match="resampling"):
        compute(
            input_path=str(input_path),
            output_dir=str(tmp_path / "out"),
            dst_crs="EPSG:3857",
            resampling="lanczos",
        )


def test_compute_missing_input(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        compute(input_path=str(tmp_path / "nope.tif"), output_dir=str(tmp_path / "out"), dst_crs="EPSG:4326")


def test_compute_rejects_source_without_crs(tmp_path: Path) -> None:
    input_path = tmp_path / "nocrs.tif"
    output_dir = tmp_path / "out"
    data = np.ones((4, 4, 4), dtype=np.uint8)
    with rasterio.open(
        input_path, "w", driver="GTiff", height=4, width=4, count=4, dtype="uint8"
    ) as dst:
        dst.write(data)

    with pytest.raises(ValueError, match="no CRS"):
        compute(input_path=str(input_path), output_dir=str(output_dir), dst_crs="EPSG:4326")

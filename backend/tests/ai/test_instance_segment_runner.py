"""SAM3 instance-segmentation runner contract tests.

The legacy LandCover/U-Net runner was removed. This module keeps the historical
test filename so downstream test selectors continue to work while validating
the replacement capability.
"""

from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from pydantic import ValidationError
from rasterio.transform import from_origin

from app.agent.tools.instance_segment.runner import _write_rgb_png, run_instance_segment
from app.agent.tools.instance_segment.schema import InstanceSegmentArguments
from app.core.settings import get_settings


IMAGERY_ID = "94e758f38ede"


def _prepare_imagery(root: Path, *, count: int = 3) -> Path:
    imagery_dir = root / IMAGERY_ID
    imagery_dir.mkdir()
    data = np.zeros((count, 4, 4), dtype=np.uint8)
    data[0] = 180
    data[1] = 90
    data[2] = 30
    with rasterio.open(
        imagery_dir / "working.tif",
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=count,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_origin(100.0, 20.0, 0.01, 0.01),
    ) as dst:
        dst.write(data)
        dst.colorinterp = (
            rasterio.enums.ColorInterp.red,
            rasterio.enums.ColorInterp.green,
            rasterio.enums.ColorInterp.blue,
        )
    (imagery_dir / "metadata.json").write_text(
        '{"bounds":[100.0,19.96,100.04,20.0]}', encoding="utf-8"
    )
    return imagery_dir


def test_schema_normalizes_and_deduplicates_concepts() -> None:
    args = InstanceSegmentArguments(
        imagery_id=IMAGERY_ID,
        concepts=[" Building ", "building", "solar   panel"],
    )
    assert args.concepts == ["building", "solar panel"]


@pytest.mark.parametrize("concept", ["", "bad/name", "line\nbreak"])
def test_schema_rejects_invalid_concepts(concept: str) -> None:
    with pytest.raises(ValidationError):
        InstanceSegmentArguments(imagery_id=IMAGERY_ID, concepts=[concept])


@pytest.mark.asyncio
async def test_runner_rejects_invalid_imagery_id() -> None:
    result = await run_instance_segment(
        InstanceSegmentArguments.model_construct(imagery_id="BADID", concepts=["building"])
    )
    assert result.error == "invalid_imagery_id"


@pytest.mark.asyncio
async def test_runner_reports_disabled_local_service(monkeypatch, tmp_path: Path) -> None:
    _prepare_imagery(tmp_path)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("SAM3_ENABLED", "false")
    get_settings.cache_clear()
    try:
        result = await run_instance_segment(
            InstanceSegmentArguments(imagery_id=IMAGERY_ID, concepts=["building"])
        )
        assert result.error == "service_disabled"
        assert result.geospatial_result is None
        assert result.artifacts == []
    finally:
        get_settings.cache_clear()


def test_rgb_export_success_keeps_documented_channel_order(tmp_path: Path) -> None:
    imagery_dir = _prepare_imagery(tmp_path)
    output = tmp_path / "input.png"
    _write_rgb_png(imagery_dir / "working.tif", output, 1, 2, 3)
    pixel = np.asarray(Image.open(output))[1, 1]
    assert pixel.tolist() == [180, 90, 30]

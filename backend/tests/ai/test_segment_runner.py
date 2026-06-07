from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError

from app.agent.tools.segment.runner import run_segment
from app.agent.tools.segment.schema import SegmentArguments
from app.core.settings import get_settings


def _write_test_tif(path: Path, *, count: int = 4) -> None:
    data = np.ones((count, 2, 2), dtype=np.uint16)
    with rasterio.open(
        path, "w", driver="GTiff", height=2, width=2, count=count, dtype="uint16"
    ) as dst:
        dst.write(data)


def test_segment_schema_rejects_duplicate_bands() -> None:
    with pytest.raises(ValidationError):
        SegmentArguments(imagery_id="94e758f38ede", red_band=2, green_band=2, blue_band=3)


def test_segment_schema_rejects_invalid_imagery_id() -> None:
    with pytest.raises(ValidationError):
        SegmentArguments(imagery_id="BADID")


def test_segment_schema_defaults() -> None:
    args = SegmentArguments(imagery_id="94e758f38ede")
    assert (args.red_band, args.green_band, args.blue_band) == (1, 2, 3)
    assert args.reason


@pytest.mark.asyncio
async def test_segment_runner_invalid_imagery_id() -> None:
    result = await run_segment(SegmentArguments.model_construct(imagery_id="BADID"))
    assert result.error == "invalid_imagery_id"


@pytest.mark.asyncio
async def test_segment_runner_imagery_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    result = await run_segment(SegmentArguments(imagery_id="94e758f38ede"))
    assert result.error == "imagery_not_found"
    get_settings.cache_clear()

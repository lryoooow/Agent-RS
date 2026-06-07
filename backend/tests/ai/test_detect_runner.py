from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError

from app.agent.tools.detect.runner import run_detect
from app.agent.tools.detect.schema import DetectArguments
from app.core.settings import get_settings
from app.mcp.client import MCPCallError


def _write_test_tif(path: Path, *, count: int = 4) -> None:
    data = np.ones((count, 2, 2), dtype=np.uint16)
    with rasterio.open(
        path, "w", driver="GTiff", height=2, width=2, count=count, dtype="uint16"
    ) as dst:
        dst.write(data)


def test_detect_schema_rejects_duplicate_bands() -> None:
    with pytest.raises(ValidationError):
        DetectArguments(imagery_id="94e758f38ede", red_band=1, green_band=1, blue_band=3)


def test_detect_schema_rejects_out_of_range_threshold() -> None:
    with pytest.raises(ValidationError):
        DetectArguments(imagery_id="94e758f38ede", score_threshold=1.5)


def test_detect_schema_defaults() -> None:
    args = DetectArguments(imagery_id="94e758f38ede")
    assert (args.red_band, args.green_band, args.blue_band) == (1, 2, 3)
    assert args.score_threshold == 0.5


@pytest.mark.asyncio
async def test_detect_runner_invalid_imagery_id() -> None:
    result = await run_detect(DetectArguments.model_construct(imagery_id="BADID"))
    assert result.error is not None


@pytest.mark.asyncio
async def test_detect_runner_imagery_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    result = await run_detect(DetectArguments(imagery_id="94e758f38ede"))
    assert result.error is not None
    get_settings.cache_clear()

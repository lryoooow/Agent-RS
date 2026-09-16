"""Contract tests for the flat ``app.agent.tools`` runners."""

from unittest.mock import AsyncMock

import pytest

from app.agent.tools.map_roi import MapROIArguments, run_map_roi
from app.services.map_roi import MapROIError


@pytest.mark.asyncio
async def test_prepare_map_roi_success(monkeypatch) -> None:
    imported = AsyncMock(
        return_value=(
            "94e758f38ede",
            {
                "preview_url": "/api/imagery/94e758f38ede/results/preview.png",
                "bounds": [120.0, 30.0, 120.1, 30.1],
            },
        )
    )
    monkeypatch.setattr("app.agent.tools.map_roi.import_map_roi", imported)
    result = await run_map_roi(MapROIArguments(bbox=(120.0, 30.0, 120.1, 30.1)))
    assert result.error is None
    assert result.geospatial_result["type"] == "preview"
    assert result.geospatial_result["imagery_id"] == "94e758f38ede"


@pytest.mark.asyncio
async def test_prepare_map_roi_invalid_source_returns_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.agent.tools.map_roi.import_map_roi",
        AsyncMock(side_effect=MapROIError("地图影像不可用")),
    )
    result = await run_map_roi(MapROIArguments(bbox=(120.0, 30.0, 120.1, 30.1)))
    assert result.error == "map_image_unavailable"
    assert result.geospatial_result is None

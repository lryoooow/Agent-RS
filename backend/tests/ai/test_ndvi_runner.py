from pathlib import Path

import numpy as np
import pytest
import rasterio

from app.agent.tools.ndvi.runner import NDVIExecutionError, _handle_docker_failure, run_ndvi
from app.agent.tools.ndvi.schema import NDVIArguments
from app.core.settings import get_settings


def _write_test_tif(path: Path, *, count: int = 4) -> None:
    data = np.ones((count, 2, 2), dtype=np.uint16)
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=2,
        width=2,
        count=count,
        dtype="uint16",
    ) as dst:
        dst.write(data)


@pytest.mark.asyncio
async def test_ndvi_runner_prefers_working_tif(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "imagery123"
    imagery_dir = tmp_path / imagery_id
    results_dir = imagery_dir / "results"
    results_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "source.tif")
    _write_test_tif(imagery_dir / "working.tif")
    (imagery_dir / "metadata.json").write_text(
        '{"crs":"EPSG:4326","bounds":[100,20,101,21]}',
        encoding="utf-8",
    )

    seen: dict[str, Path] = {}

    async def fake_run_ndvi_execution(source_path, output_dir, *_):
        seen["source_path"] = source_path
        seen["output_dir"] = output_dir
        return (
            {"min": 0.1, "max": 0.8, "mean": 0.4, "std": 0.2},
            {"mode": "docker_mcp", "fallback_used": False, "error_code": None},
        )

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.agent.tools.ndvi.runner._run_ndvi_execution", fake_run_ndvi_execution)

    result = await run_ndvi(NDVIArguments(imagery_id=imagery_id))

    assert result.error is None
    assert seen["source_path"] == imagery_dir / "working.tif"
    assert seen["output_dir"] == results_dir
    assert result.geospatial_result
    assert result.geospatial_result["type"] == "ndvi"
    assert result.geospatial_result["execution"]["mode"] == "docker_mcp"


@pytest.mark.asyncio
async def test_ndvi_runner_rejects_invalid_band_before_execution(monkeypatch, tmp_path: Path) -> None:
    imagery_id = "94e758f38ede"
    imagery_dir = tmp_path / imagery_id
    imagery_dir.mkdir(parents=True)
    _write_test_tif(imagery_dir / "working.tif", count=4)

    async def fail_if_called(*_args, **_kwargs):
        raise AssertionError("NDVI execution should not run for invalid bands")

    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr("app.agent.tools.ndvi.runner._run_ndvi_execution", fail_if_called)

    result = await run_ndvi(
        NDVIArguments.model_construct(imagery_id=imagery_id, red_band=0, nir_band=4, reason="test")
    )

    assert result.error == "invalid_bands"
    assert "波段索引必须从 1 开始" in result.tool_context


@pytest.mark.asyncio
async def test_ndvi_docker_failure_respects_disabled_local_fallback(monkeypatch, tmp_path: Path) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "ndvi_mcp_allow_local_fallback", False)

    with pytest.raises(NDVIExecutionError) as exc_info:
        await _handle_docker_failure(
            RuntimeError("docker failed"),
            "mcp_error",
            tmp_path / "source.tif",
            tmp_path / "results",
            NDVIArguments(imagery_id="94e758f38ede"),
            settings,
        )

    assert exc_info.value.code == "mcp_error"

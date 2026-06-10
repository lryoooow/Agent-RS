from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import rasterio
from pydantic import ValidationError

from app.agent.tools.ocr.runner import run_ocr
from app.agent.tools.ocr.schema import OcrArguments
from app.core.settings import get_settings


def _write_test_tif(path: Path, *, count: int = 3) -> None:
    data = np.ones((count, 2, 2), dtype=np.uint16)
    with rasterio.open(
        path, "w", driver="GTiff", height=2, width=2, count=count, dtype="uint16"
    ) as dst:
        dst.write(data)


# ---------- schema ----------

def test_ocr_schema_defaults() -> None:
    args = OcrArguments(imagery_id="94e758f38ede")
    assert (args.red_band, args.green_band, args.blue_band) == (1, 2, 3)
    assert args.grayscale is False
    assert args.max_dimension == 2048
    assert args.min_confidence == 0.0
    assert args.reason


def test_ocr_schema_rejects_invalid_imagery_id() -> None:
    with pytest.raises(ValidationError):
        OcrArguments(imagery_id="BADID")


def test_ocr_schema_rejects_duplicate_rgb_bands() -> None:
    with pytest.raises(ValidationError):
        OcrArguments(imagery_id="94e758f38ede", red_band=1, green_band=1, blue_band=3)


def test_ocr_schema_grayscale_allows_repeated_bands() -> None:
    # 灰度模式只用 red_band，不应因 RGB 重复而报错。
    args = OcrArguments(imagery_id="94e758f38ede", grayscale=True, red_band=1, green_band=1, blue_band=1)
    assert args.grayscale is True


def test_ocr_schema_rejects_band_below_one() -> None:
    with pytest.raises(ValidationError):
        OcrArguments(imagery_id="94e758f38ede", red_band=0)


def test_ocr_schema_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValidationError):
        OcrArguments(imagery_id="94e758f38ede", min_confidence=1.5)


# ---------- runner 边界/错误路径 ----------

@pytest.mark.asyncio
async def test_ocr_runner_invalid_imagery_id() -> None:
    result = await run_ocr(OcrArguments.model_construct(imagery_id="BADID"))
    assert result.error == "invalid_imagery_id"


@pytest.mark.asyncio
async def test_ocr_runner_imagery_not_found(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()
    result = await run_ocr(OcrArguments(imagery_id="94e758f38ede"))
    assert result.error == "imagery_not_found"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ocr_runner_invalid_bands(monkeypatch, tmp_path: Path) -> None:
    # 影像只有 3 个波段，请求 blue_band=9 应触发波段校验失败。
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif", count=3)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    get_settings.cache_clear()

    result = await run_ocr(OcrArguments(imagery_id="94e758f38ede", blue_band=9))

    assert result.error == "invalid_bands"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ocr_runner_mcp_disabled(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_DOC_MCP_USE_DOCKER", "false")
    get_settings.cache_clear()

    result = await run_ocr(OcrArguments(imagery_id="94e758f38ede"))

    assert result.error == "mcp_disabled"
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ocr_runner_mcp_error(monkeypatch, tmp_path: Path) -> None:
    from app.mcp.client import MCPCallError

    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_DOC_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    class _RaisingClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def call_tool(self, *a, **k):
            raise MCPCallError("boom")

    monkeypatch.setattr("app.agent.tools.ocr.runner.RSToolsMCPClient", _RaisingClient)

    result = await run_ocr(OcrArguments(imagery_id="94e758f38ede"))

    assert result.error == "mcp_error"
    assert result.metadata["error_code"] == "mcp_error"
    get_settings.cache_clear()


# ---------- runner 成功路径 ----------

@pytest.mark.asyncio
async def test_ocr_runner_success(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_DOC_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    stub_stats = {
        "full_text": "中国遥感卫星地面站\nBeijing 2026",
        "blocks": [
            {"text": "中国遥感卫星地面站", "confidence": 0.95, "box": [[0, 0], [1, 0], [1, 1], [0, 1]]},
            {"text": "Beijing 2026", "confidence": 0.88, "box": [[0, 2], [1, 2], [1, 3], [0, 3]]},
        ],
        "block_count": 2,
        "char_count": 21,
        "avg_confidence": 0.915,
        "min_confidence_seen": 0.88,
        "grayscale": False,
    }

    captured: dict = {}

    class _OkClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def call_tool(self, tool_name, *, source_path, output_dir, arguments):
            captured["tool_name"] = tool_name
            captured["arguments"] = arguments
            return stub_stats

    monkeypatch.setattr("app.agent.tools.ocr.runner.RSToolsMCPClient", _OkClient)

    result = await run_ocr(OcrArguments(imagery_id="94e758f38ede"))

    assert result.error is None
    assert captured["tool_name"] == "ocr_recognize"
    assert captured["arguments"] == {
        "red_band": 1,
        "green_band": 2,
        "blue_band": 3,
        "grayscale": False,
        "max_dimension": 2048,
        "min_confidence": 0.0,
    }
    assert result.result_count == 2
    geo = result.geospatial_result
    assert geo["type"] == "ocr"
    assert geo["stats"]["block_count"] == 2
    assert geo["stats"]["avg_confidence"] == 0.915
    assert result.artifacts and result.artifacts[0].type == "geospatial"
    assert result.metadata["execution_mode"] == "docker_mcp"
    assert "中国遥感卫星地面站" in result.tool_context
    assert "OCR" in result.tool_context
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ocr_runner_grayscale_passes_single_band(monkeypatch, tmp_path: Path) -> None:
    # 灰度模式只校验 red_band，payload 仍透传 grayscale=True。
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif", count=1)
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_DOC_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    captured: dict = {}

    class _OkClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def call_tool(self, tool_name, *, source_path, output_dir, arguments):
            captured["arguments"] = arguments
            return {"full_text": "扫描件", "blocks": [], "block_count": 1, "char_count": 3,
                    "avg_confidence": 0.9, "min_confidence_seen": 0.9, "grayscale": True}

    monkeypatch.setattr("app.agent.tools.ocr.runner.RSToolsMCPClient", _OkClient)

    result = await run_ocr(OcrArguments(imagery_id="94e758f38ede", grayscale=True, red_band=1))

    assert result.error is None
    assert captured["arguments"]["grayscale"] is True
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ocr_runner_truncates_long_text(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_DOC_MCP_USE_DOCKER", "true")
    monkeypatch.setenv("AI_CONTEXT_MAX_TOOL_CHARS", "50")
    get_settings.cache_clear()

    long_text = "字" * 500
    stub_stats = {
        "full_text": long_text,
        "blocks": [{"text": long_text, "confidence": 0.9, "box": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
        "block_count": 1,
        "char_count": 500,
        "avg_confidence": 0.9,
        "min_confidence_seen": 0.9,
        "grayscale": False,
    }

    class _OkClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def call_tool(self, *a, **k):
            return stub_stats

    monkeypatch.setattr("app.agent.tools.ocr.runner.RSToolsMCPClient", _OkClient)

    result = await run_ocr(OcrArguments(imagery_id="94e758f38ede"))

    assert result.error is None
    assert "仅返回前 50 字" in result.tool_context
    # 截断后正文不应包含完整 500 字。
    assert result.tool_context.count("字") < 500
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_ocr_runner_empty_result(monkeypatch, tmp_path: Path) -> None:
    imagery_dir = tmp_path / "94e758f38ede"
    imagery_dir.mkdir()
    _write_test_tif(imagery_dir / "working.tif")
    monkeypatch.setenv("IMAGERY_UPLOAD_DIR", str(tmp_path))
    monkeypatch.setenv("RS_DOC_MCP_USE_DOCKER", "true")
    get_settings.cache_clear()

    stub_stats = {
        "full_text": "",
        "blocks": [],
        "block_count": 0,
        "char_count": 0,
        "avg_confidence": 0.0,
        "min_confidence_seen": 0.0,
        "grayscale": False,
    }

    class _OkClient:
        def __init__(self, *a, **k) -> None:
            pass

        async def call_tool(self, *a, **k):
            return stub_stats

    monkeypatch.setattr("app.agent.tools.ocr.runner.RSToolsMCPClient", _OkClient)

    result = await run_ocr(OcrArguments(imagery_id="94e758f38ede"))

    assert result.error is None
    assert result.result_count == 0
    assert "未识别到任何文字" in result.tool_context
    get_settings.cache_clear()

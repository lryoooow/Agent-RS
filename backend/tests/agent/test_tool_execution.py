"""tool_execution.py 直接测试：安全关键管线的前置校验与执行顺序。

prepare_tool_call 是鉴权 + 参数校验的入口，此前所有测试都把它
的依赖 mock 掉，从未直接验证三种拒绝路径的返回结构。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from app.agent.tool_execution import (
    PreparedTool,
    PrepareRejected,
    prepare_tool_call,
    run_prepared_tool,
)
from app.agent.tool_registry import RegisteredTool
from app.agent.types import ToolRunResult


class FakeArgs(BaseModel):
    imagery_id: str = "img-001"


def _fake_tool(*, enabled: bool = True) -> RegisteredTool:
    tool = MagicMock(spec=RegisteredTool)
    tool.name = "calculate_ndvi"
    tool.is_enabled.return_value = enabled
    tool.argument_model = FakeArgs
    tool.runner = AsyncMock(return_value=ToolRunResult(tool_context="NDVI=0.42"))
    return tool


# ================================================================ prepare_tool_call


@pytest.mark.asyncio
async def test_prepare_rejects_unavailable_tool(monkeypatch) -> None:
    """工具不存在 → failure=tool_unavailable。"""
    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda name: None)

    result = await prepare_tool_call("nonexistent", {}, user_id="u1")

    assert isinstance(result, PrepareRejected)
    assert result.failure == "tool_unavailable"
    assert result.result.metadata["error_code"] == "tool_unavailable"


@pytest.mark.asyncio
async def test_prepare_rejects_disabled_tool(monkeypatch) -> None:
    """工具存在但未启用 → failure=tool_unavailable。"""
    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda name: _fake_tool(enabled=False))

    result = await prepare_tool_call("disabled_tool", {}, user_id="u1")

    assert isinstance(result, PrepareRejected)
    assert result.failure == "tool_unavailable"


@pytest.mark.asyncio
async def test_prepare_rejects_invalid_arguments(monkeypatch) -> None:
    """参数校验失败 → failure=invalid_arguments。"""
    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda name: _fake_tool())

    # imagery_id 类型不对（传 int 而非 str），但 FakeArgs 会做 coerce；
    # 传一个真正缺字段或类型不兼容的 case
    class StrictArgs(BaseModel):
        imagery_id: str
        band_combo: list[str]

    tool = _fake_tool()
    tool.argument_model = StrictArgs
    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda name: tool)

    result = await prepare_tool_call("calculate_ndvi", {"imagery_id": "img-001"}, user_id="u1")

    assert isinstance(result, PrepareRejected)
    assert result.failure == "invalid_arguments"
    assert result.result.metadata["error_code"] == "invalid_arguments"


@pytest.mark.asyncio
async def test_prepare_rejects_access_denied(monkeypatch) -> None:
    """鉴权失败 → failure=access_denied。"""
    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda name: _fake_tool())
    monkeypatch.setattr(
        "app.agent.tool_execution.validate_tool_access",
        AsyncMock(return_value="not_owner"),
    )

    result = await prepare_tool_call("calculate_ndvi", {"imagery_id": "img-001"}, user_id="u1")

    assert isinstance(result, PrepareRejected)
    assert result.failure == "access_denied"
    assert result.result.metadata["error_code"] == "not_owner"


@pytest.mark.asyncio
async def test_prepare_success(monkeypatch) -> None:
    """全部校验通过 → 返回 PreparedTool。"""
    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda name: _fake_tool())
    monkeypatch.setattr(
        "app.agent.tool_execution.validate_tool_access",
        AsyncMock(return_value=None),
    )

    result = await prepare_tool_call("calculate_ndvi", {"imagery_id": "img-001"}, user_id="u1")

    assert isinstance(result, PreparedTool)
    assert result.name == "calculate_ndvi"
    assert result.user_id == "u1"
    assert result.imagery_id == "img-001"


# ================================================================ run_prepared_tool


@pytest.mark.asyncio
async def test_run_prepared_tool_calls_runner_and_finishes_job(monkeypatch) -> None:
    """正常执行：begin_job → heartbeat → runner → finish_job。"""
    tool = _fake_tool()
    prepared = PreparedTool(tool=tool, arguments=FakeArgs(), user_id="u1")

    monkeypatch.setattr("app.agent.tool_execution.begin_tool_job", AsyncMock(return_value="job-1"))
    monkeypatch.setattr("app.agent.tool_execution.finish_tool_job", AsyncMock())
    # heartbeat_tool_job 是 async context manager
    heartbeat_cm = MagicMock()
    heartbeat_cm.__aenter__ = AsyncMock(return_value=None)
    heartbeat_cm.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("app.agent.tool_execution.heartbeat_tool_job", lambda job_id: heartbeat_cm)
    monkeypatch.setattr("app.agent.tool_execution.stage_imagery", _noop_stage)

    result = await run_prepared_tool(prepared)

    assert result.error is None
    assert result.tool_context == "NDVI=0.42"
    tool.runner.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_prepared_tool_catches_runner_exception(monkeypatch) -> None:
    """runner 抛异常 → 不外泄，转成带 tool_runner_exception 的失败结果。"""
    tool = _fake_tool()
    tool.runner = AsyncMock(side_effect=RuntimeError("GPU OOM"))
    prepared = PreparedTool(tool=tool, arguments=FakeArgs(), user_id="u1")

    monkeypatch.setattr("app.agent.tool_execution.begin_tool_job", AsyncMock(return_value=None))
    monkeypatch.setattr("app.agent.tool_execution.finish_tool_job", AsyncMock())
    heartbeat_cm = MagicMock()
    heartbeat_cm.__aenter__ = AsyncMock(return_value=None)
    heartbeat_cm.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr("app.agent.tool_execution.heartbeat_tool_job", lambda job_id: heartbeat_cm)
    monkeypatch.setattr("app.agent.tool_execution.stage_imagery", _noop_stage)

    result = await run_prepared_tool(prepared)

    assert result.error is not None
    assert "GPU OOM" in result.error
    assert result.metadata["error_code"] == "tool_runner_exception"


class _NoopStage:
    """stage_imagery 的空 async context manager（无影像 ID 时不进入 staging）。"""
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False


def _noop_stage(imagery_id: str):
    return _NoopStage()

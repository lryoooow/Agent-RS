"""tool_execution.py 直接测试：安全关键管线的前置校验与执行顺序。

prepare_tool_call 是鉴权 + 参数校验的入口，此前所有测试都把它
的依赖 mock 掉，从未直接验证三种拒绝路径的返回结构。
"""
from __future__ import annotations

import asyncio
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
async def test_run_prepared_tool_catches_runner_exception(monkeypatch, caplog) -> None:
    """runner 抛异常 → 不外泄，转成带 tool_runner_exception 的失败结果。"""
    tool = _fake_tool()
    secret = "GPU OOM signed_url=https://storage.example/?token=TOP_SECRET"
    tool.runner = AsyncMock(side_effect=RuntimeError(secret))
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
    assert secret not in result.error
    assert secret not in result.tool_context
    assert secret not in caplog.text
    assert result.metadata["error_code"] == "tool_runner_exception"
    assert result.metadata["exception_type"] == "RuntimeError"
    assert len(result.metadata["diagnostic_id"]) == 16


class _NoopStage:
    """stage_imagery 的空 async context manager（无影像 ID 时不进入 staging）。"""
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False


def _noop_stage(imagery_id: str, *, user_id=None):
    return _NoopStage()


@pytest.fixture
def isolated_job_lifecycle(monkeypatch):
    begin = AsyncMock(return_value="job-1")
    finish = AsyncMock()
    interrupt = AsyncMock()
    monkeypatch.setattr("app.agent.tool_execution.begin_tool_job", begin)
    monkeypatch.setattr("app.agent.tool_execution.finish_tool_job", finish)
    monkeypatch.setattr("app.agent.tool_execution.interrupt_tool_job", interrupt)
    monkeypatch.setattr("app.agent.tool_execution.heartbeat_tool_job", lambda _: _NoopStage())
    monkeypatch.setattr("app.agent.tool_execution.stage_imagery", _noop_stage)
    return begin, finish, interrupt


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["registration", "staging", "runner"])
async def test_cancel_records_known_id_and_distinguishes_unstarted_execution(monkeypatch, isolated_job_lifecycle, phase):
    begin, finish, interrupt = isolated_job_lifecycle
    started = asyncio.Event()
    tool = _fake_tool()

    async def blocking(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    if phase == "registration":
        begin.side_effect = blocking
    elif phase == "staging":
        class BlockingStage(_NoopStage):
            async def __aenter__(self):
                await blocking()
        monkeypatch.setattr("app.agent.tool_execution.stage_imagery", lambda _, **kwargs: BlockingStage())
    else:
        tool.runner.side_effect = blocking
    task = asyncio.create_task(run_prepared_tool(PreparedTool(tool=tool, arguments=FakeArgs(), user_id="u1")))
    await asyncio.wait_for(started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    interrupt.assert_awaited_once()
    assert interrupt.await_args.kwargs["outcome_unknown"] is (phase == "runner")
    if phase == "registration":
        assert interrupt.await_args.args[0] == begin.await_args.kwargs["job_id"]
    else:
        assert interrupt.await_args.args[0] == "job-1"
    finish.assert_not_awaited()
    if phase != "runner":
        tool.runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancellation_during_result_write_preserves_completed_result(isolated_job_lifecycle):
    _, finish, interrupt = isolated_job_lifecycle
    entered = asyncio.Event()

    async def write(*args, **kwargs):
        if finish.await_count == 1:
            entered.set()
            await asyncio.Event().wait()

    finish.side_effect = write
    tool = _fake_tool()
    task = asyncio.create_task(run_prepared_tool(PreparedTool(tool=tool, arguments=FakeArgs(), user_id="u1")))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert finish.await_count == 2
    assert finish.await_args.args[1] is tool.runner.return_value
    interrupt.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_during_staging_publish_is_not_marked_complete(monkeypatch, isolated_job_lifecycle):
    _, finish, interrupt = isolated_job_lifecycle
    entered = asyncio.Event()

    class PublishingStage(_NoopStage):
        async def __aexit__(self, *args):
            entered.set()
            await asyncio.Event().wait()

    monkeypatch.setattr("app.agent.tool_execution.stage_imagery", lambda _, **kwargs: PublishingStage())
    task = asyncio.create_task(run_prepared_tool(PreparedTool(tool=_fake_tool(), arguments=FakeArgs(), user_id="u1")))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    interrupt.assert_awaited_once_with("job-1", outcome_unknown=True, expected_attempt=1)
    finish.assert_not_awaited()


@pytest.mark.asyncio
async def test_repeated_cancel_cannot_interrupt_short_terminal_write(isolated_job_lifecycle):
    _, _, interrupt = isolated_job_lifecycle
    running, writing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def runner(*args):
        running.set()
        await asyncio.Event().wait()

    async def write(*args, **kwargs):
        writing.set()
        await release.wait()

    tool = _fake_tool()
    tool.runner.side_effect = runner
    interrupt.side_effect = write
    task = asyncio.create_task(run_prepared_tool(PreparedTool(tool=tool, arguments=FakeArgs(), user_id="u1")))
    await asyncio.wait_for(running.wait(), 1)
    task.cancel()
    await asyncio.wait_for(writing.wait(), 1)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    interrupt.assert_awaited_once_with("job-1", outcome_unknown=True, expected_attempt=1)


@pytest.mark.asyncio
async def test_terminal_write_timeout_is_bounded_and_cancellation_still_propagates(monkeypatch, isolated_job_lifecycle, caplog):
    _, _, interrupt = isolated_job_lifecycle
    running = asyncio.Event()

    async def wait(*args, **kwargs):
        running.set()
        await asyncio.Event().wait()

    tool = _fake_tool()
    tool.runner.side_effect = wait
    interrupt.side_effect = wait
    monkeypatch.setattr("app.agent.tool_execution._CANCEL_FINALIZE_SECONDS", 0.01)
    task = asyncio.create_task(run_prepared_tool(PreparedTool(tool=tool, arguments=FakeArgs(), user_id="u1")))
    await asyncio.wait_for(running.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 1)
    assert "tool.cancel_finalize_failed" in caplog.text


@pytest.mark.asyncio
async def test_publication_failure_is_failed_with_no_success_artifacts(monkeypatch):
    from contextlib import asynccontextmanager
    from app.agent.tools.staging import ArtifactPublicationError
    import app.agent.tool_execution as execution
    @asynccontextmanager
    async def failed_publication(*args, **kwargs):
        yield
        raise ArtifactPublicationError()
    finish = AsyncMock()
    monkeypatch.setattr(execution, "stage_imagery", failed_publication)
    monkeypatch.setattr(execution, "finish_tool_job", finish)
    tool = _fake_tool()
    tool.runner = AsyncMock(return_value=ToolRunResult(tool_context="computed", geospatial_result={
        "type": "ndvi", "result_url": "/results/not_uploaded.png",
    }))
    prepared = PreparedTool(tool=tool, arguments=FakeArgs(imagery_id="img-001"), user_id="u1")
    result = await execution.run_prepared_tool(prepared)
    assert result.metadata["error_code"] == "artifact_publication_failed"
    assert result.error
    assert result.geospatial_result is None
    assert result.artifacts == []
    assert finish.await_args.args[1] is result


@pytest.mark.asyncio
async def test_persisted_tool_arguments_do_not_turn_defaults_into_explicit_inputs(monkeypatch):
    import app.agent.tool_execution as execution
    from app.agent.tools.ndvi.schema import NDVIArguments
    begin = AsyncMock(return_value=None)
    monkeypatch.setattr(execution, "begin_tool_job", begin)
    args = NDVIArguments(imagery_id="abc123def456")
    prepared = PreparedTool(tool=_fake_tool(), arguments=args, user_id="u1")
    await execution.run_prepared_tool(prepared)
    assert begin.await_args.kwargs["arguments"] == {"imagery_id": "abc123def456"}


@pytest.mark.asyncio
async def test_report_does_not_stage_entire_source_image(monkeypatch):
    import app.agent.tool_execution as execution
    stage = MagicMock(side_effect=AssertionError("report must not fetch source.tif"))
    monkeypatch.setattr(execution, "stage_imagery", stage)
    tool = _fake_tool()
    tool.name = "generate_report"
    result = await execution.run_prepared_tool(PreparedTool(tool=tool, arguments=FakeArgs(imagery_id="img-001"), user_id="u1"))
    assert not result.error
    stage.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["access_denied", "storage_unavailable"])
async def test_staging_failure_preserves_code_and_never_starts_runner(monkeypatch, code):
    from contextlib import asynccontextmanager
    from app.agent.tools.staging import ImageryStagingError
    import app.agent.tool_execution as execution
    received = {}

    @asynccontextmanager
    async def fail_before_read(imagery_id, *, user_id):
        received.update(imagery_id=imagery_id, user_id=user_id)
        raise ImageryStagingError(code, "影像校验失败，本次未执行分析。")
        yield  # pragma: no cover

    monkeypatch.setattr(execution, "stage_imagery", fail_before_read)
    monkeypatch.setattr(execution, "begin_tool_job", AsyncMock(return_value="job-staging"))
    monkeypatch.setattr(execution, "heartbeat_tool_job", lambda _: _NoopStage())
    finish = AsyncMock()
    monkeypatch.setattr(execution, "finish_tool_job", finish)
    tool = _fake_tool()
    result = await run_prepared_tool(PreparedTool(tool=tool, arguments=FakeArgs(), user_id="u1"))
    assert received == {"imagery_id": "img-001", "user_id": "u1"}
    tool.runner.assert_not_awaited()
    assert result.metadata["error_code"] == code
    assert result.geospatial_result is None
    finish.assert_awaited_once_with("job-staging", result)

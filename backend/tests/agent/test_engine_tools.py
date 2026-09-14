"""engine/tools.py：AutoGen 工具包装的安全与行为测试。

重点不是"能跑通"，而是几条**不能退化**的性质：
- 鉴权在每一次调用上都生效（多步链路的每一步都是独立的攻击面）
- 身份取自 contextvar，且未登录时不会被回退成默认用户
- GPU 配额按回合生效，超限返回文本而不是抛异常
- 产物进回合收集器，不混进给模型的文本
"""
from __future__ import annotations

import pytest
from autogen_core import CancellationToken

from app.agent.engine.tools import RemoteSensingTool, build_tools
from app.agent.engine.turn_context import turn_scope
from app.agent.tool_registry import RegisteredTool
from app.agent.tools.detect.schema import DETECT_TOOL_NAME, DetectArguments
from app.agent.tools.ndvi.schema import NDVI_TOOL_DESCRIPTION, NDVI_TOOL_NAME, NDVIArguments
from app.agent.tools.schema_gen import build_function_definition
from app.agent.types import ToolRunResult
from app.auth import reset_current_user_id, set_current_user_id
from app.core.settings import get_settings
from app.schemas.chat import GeospatialNDVIResult

OWNER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _no_database(monkeypatch):
    """本组只测工具包装逻辑，不该依赖库是否起着。

    关掉存储后 durable 队列（begin_tool_job）走 no-op 分支，避免用例因
    docker compose 没起而连 127.0.0.1:15432 失败、拖慢并污染日志。
    """
    monkeypatch.setenv("DATABASE_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def as_owner():
    token = set_current_user_id(OWNER)
    yield OWNER
    reset_current_user_id(token)


def _ndvi_tool(runner) -> RegisteredTool:
    return RegisteredTool(
        name="calculate_ndvi",
        definition=build_function_definition(
            NDVI_TOOL_NAME, NDVI_TOOL_DESCRIPTION, NDVIArguments
        ),
        argument_model=NDVIArguments,
        runner=runner,
        agent_name="spectral_agent",
        resource_kind="imagery",
    )


def _detect_tool(runner) -> RegisteredTool:
    return RegisteredTool(
        name="detect_objects",
        definition=build_function_definition(
            DETECT_TOOL_NAME, "目标检测测试工具", DetectArguments
        ),
        argument_model=DetectArguments,
        runner=runner,
        agent_name="detection_agent",
        resource_kind="imagery",
    )


async def _ok_runner(_args) -> ToolRunResult:
    return ToolRunResult(
        tool_context="NDVI 均值 0.42",
        geospatial_result=GeospatialNDVIResult(
            type="ndvi",
            imagery_id="94e758f38ede",
            result_url="/api/imagery/94e758f38ede/results/ndvi.png",
            stats={"mean": 0.42, "min": -0.2, "max": 0.9, "std": 0.15},
        ),
    )


@pytest.mark.asyncio
async def test_tool_returns_context_text_and_collects_artifacts(
    monkeypatch, as_owner
) -> None:
    """给模型的是文本摘要；图层产物走回合收集器，不混进文本。"""
    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda _n: _ndvi_tool(_ok_runner))
    monkeypatch.setattr(
        "app.agent.tool_execution.validate_tool_access",
        _always_allow,
    )
    tool = RemoteSensingTool(_ndvi_tool(_ok_runner))

    with turn_scope() as state:
        text = await tool.run(
            NDVIArguments(imagery_id="94e758f38ede"), CancellationToken()
        )

    assert text == "NDVI 均值 0.42"
    assert "layers" not in text and "geospatial" not in text
    assert len(state.invocations) == 1
    assert state.latest_geospatial_result() is not None


async def _always_allow(_name, _args, _user_id):
    return None


@pytest.mark.asyncio
async def test_access_denied_never_runs_the_runner(monkeypatch, as_owner) -> None:
    """归属校验不通过时 runner 绝不能被执行。"""

    async def fail_runner(_args):
        raise AssertionError("runner 不应在鉴权失败时执行")

    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda _n: _ndvi_tool(fail_runner))

    async def deny(_name, _args, _user_id):
        return "imagery_not_found_or_forbidden"

    monkeypatch.setattr("app.agent.tool_execution.validate_tool_access", deny)
    tool = RemoteSensingTool(_ndvi_tool(fail_runner))

    with turn_scope():
        text = await tool.run(NDVIArguments(imagery_id="aaaaaaaaaaaa"), CancellationToken())

    assert "无权访问" in text
    assert "不要编造结果" in text  # 防止模型假装执行过


@pytest.mark.asyncio
async def test_guard_runs_on_every_call_not_just_the_first(monkeypatch, as_owner) -> None:
    """多步链路的每一步都要独立鉴权——中间步骤的参数是模型现编的。"""
    seen: list[str] = []

    async def recording_guard(_name, args, _user_id):
        seen.append(str(args.get("imagery_id")))
        return None

    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda _n: _ndvi_tool(_ok_runner))
    monkeypatch.setattr("app.agent.tool_execution.validate_tool_access", recording_guard)
    tool = RemoteSensingTool(_ndvi_tool(_ok_runner))

    with turn_scope():
        for imagery_id in ("aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"):
            await tool.run(NDVIArguments(imagery_id=imagery_id), CancellationToken())

    assert seen == ["aaaaaaaaaaaa", "bbbbbbbbbbbb", "cccccccccccc"], (
        "每一步都必须过一次 guard，不能只校验第一步"
    )


@pytest.mark.asyncio
async def test_identity_comes_from_contextvar_and_does_not_fall_back(monkeypatch) -> None:
    """未设置身份时必须传 None 给 guard，不能回退成 default_user_id。"""
    captured: list[str | None] = []

    async def capture_guard(_name, _args, user_id):
        captured.append(user_id)
        return None

    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda _n: _ndvi_tool(_ok_runner))
    monkeypatch.setattr("app.agent.tool_execution.validate_tool_access", capture_guard)
    tool = RemoteSensingTool(_ndvi_tool(_ok_runner))

    with turn_scope():
        await tool.run(NDVIArguments(imagery_id="94e758f38ede"), CancellationToken())
    assert captured == [None], (
        "未登录时 user_id 必须是 None；若回退成 default_user_id，"
        "tool_guards 就不会返回 owner_required，等于匿名放行"
    )

    captured.clear()
    token = set_current_user_id(OWNER)
    try:
        with turn_scope():
            await tool.run(NDVIArguments(imagery_id="94e758f38ede"), CancellationToken())
    finally:
        reset_current_user_id(token)
    assert captured == [OWNER]


@pytest.mark.asyncio
async def test_gpu_budget_blocks_second_call_without_raising(monkeypatch, as_owner) -> None:
    """GPU 工具超配额时返回说明文本，让模型自己收敛，不抛异常炸链路。"""
    runs = 0

    async def counting_runner(_args) -> ToolRunResult:
        nonlocal runs
        runs += 1
        return ToolRunResult(tool_context="检出 3 个目标")

    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda _n: _detect_tool(counting_runner))
    monkeypatch.setattr("app.agent.tool_execution.validate_tool_access", _always_allow)
    tool = RemoteSensingTool(_detect_tool(counting_runner))

    limit = get_settings().agent_max_gpu_tool_calls
    with turn_scope() as state:
        first = await tool.run(DetectArguments(imagery_id="94e758f38ede"), CancellationToken())
        second = await tool.run(DetectArguments(imagery_id="94e758f38ede"), CancellationToken())

    assert first == "检出 3 个目标"
    assert "已达上限" in second
    assert runs == limit, f"超配额后 runner 不应再执行，实际执行了 {runs} 次"
    assert state.gpu_calls == limit


@pytest.mark.asyncio
async def test_gpu_budget_is_per_turn(monkeypatch, as_owner) -> None:
    """配额按回合重置——并发请求之间不能互相影响。"""

    async def runner(_args) -> ToolRunResult:
        return ToolRunResult(tool_context="ok")

    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda _n: _detect_tool(runner))
    monkeypatch.setattr("app.agent.tool_execution.validate_tool_access", _always_allow)
    tool = RemoteSensingTool(_detect_tool(runner))

    for _ in range(3):
        with turn_scope() as state:
            text = await tool.run(DetectArguments(imagery_id="94e758f38ede"), CancellationToken())
            assert text == "ok", "新回合应重新拿到配额"
            assert state.gpu_calls == 1


def test_build_tools_exposes_every_enabled_tool() -> None:
    from app.agent.tool_registry import TOOLS

    tools = build_tools()
    expected = {name for name, t in TOOLS.items() if t.is_enabled()}
    assert {t.name for t in tools} == expected


def test_tool_schema_comes_from_the_pydantic_model() -> None:
    """AutoGen 暴露给模型的 schema 必须就是项目已有的参数模型，不能另写一份。"""
    tool = RemoteSensingTool(_ndvi_tool(_ok_runner))
    schema = tool.schema
    assert schema["name"] == "calculate_ndvi"
    assert "imagery_id" in schema["parameters"]["properties"]
    assert "imagery_id" in schema["parameters"]["required"]


@pytest.mark.asyncio
async def test_gpu_budget_holds_under_parallel_tool_calls(monkeypatch, as_owner) -> None:
    """AutoGen 一个回合里的多个工具调用是 asyncio.gather **并行**跑的
    （`_assistant_agent.py:1200`）。

    「执行前查计数、执行完再加计数」这种写法下，同时发起的两个 GPU 工具会双双通过
    检查，配额形同虚设——而并行占住两块 GPU 恰恰是最该拦的情况。
    所以配额必须先占后用。
    """
    import asyncio

    running = 0
    peak = 0

    async def slow_runner(_args) -> ToolRunResult:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.05)
        running -= 1
        return ToolRunResult(tool_context="检出 3 个目标")

    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda _n: _detect_tool(slow_runner))
    monkeypatch.setattr("app.agent.tool_execution.validate_tool_access", _always_allow)
    tool = RemoteSensingTool(_detect_tool(slow_runner))

    limit = get_settings().agent_max_gpu_tool_calls
    with turn_scope():
        results = await asyncio.gather(
            tool.run(DetectArguments(imagery_id="94e758f38ede"), CancellationToken()),
            tool.run(DetectArguments(imagery_id="94e758f38ede"), CancellationToken()),
        )

    assert peak <= limit, f"并行下同时在跑的 GPU 工具数 {peak} 超过配额 {limit}"
    assert sum(1 for r in results if "已达上限" in r) == 2 - limit


@pytest.mark.asyncio
async def test_rejected_call_gives_the_gpu_slot_back(monkeypatch, as_owner) -> None:
    """名额是执行前占的，鉴权/参数被拒时没真跑，必须还回去。

    否则一次 ID 写错就白白吃掉本轮唯一的 GPU 配额，后面正确的调用反而做不了。
    """

    async def runner(_args) -> ToolRunResult:
        return ToolRunResult(tool_context="检出 3 个目标")

    monkeypatch.setattr("app.agent.tool_execution.get_tool", lambda _n: None)  # tool_unavailable
    tool = RemoteSensingTool(_detect_tool(runner))

    with turn_scope() as state:
        rejected = await tool.run(DetectArguments(imagery_id="94e758f38ede"), CancellationToken())
        assert "未执行" in rejected
        assert state.gpu_calls == 0, "被拒的调用不该占用配额"

"""AutoGen 所有工具调用共用的确定性执行管线。

## 为什么要抽出来

工具执行不只是"调 runner"，它是一条安全关键的管线：

    工具可用性 → 参数模型校验 → 资源归属鉴权 → durable 队列登记
    → 影像 staging → runner → 终态落库

其中「归属鉴权」和「durable 队列」是安全关键边界。所有 AutoGen Tool 包装器都必须
经过这一个实现，避免任何 Agent 绕过 `validate_tool_access` 越权访问资源。

## 为什么拆成 prepare / run 两段

校验完成之后、真正执行之前需要发 `child_agent_running`、`tool_execution_started` 等
前端契约事件，因此拆成 prepare / run 两段。事件桥在两段之间发状态，管线本身不碰 trace。

本模块不 import autogen，保持确定性和可独立测试。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from app.agent.tool_guards import validate_tool_access
from app.agent.tool_jobs import begin_tool_job, finish_tool_job, heartbeat_tool_job
from app.agent.tool_registry import RegisteredTool, get_tool
from app.agent.tools.staging import stage_imagery
from app.agent.types import ToolRunResult

logger = logging.getLogger(__name__)

PrepareFailure = Literal["tool_unavailable", "invalid_arguments", "access_denied", "analysis_precondition"]


@dataclass(frozen=True)
class PreparedTool:
    """通过全部前置校验、可以安全执行的工具调用。"""

    tool: RegisteredTool
    arguments: BaseModel
    user_id: str | None

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def imagery_id(self) -> str:
        return str(self.arguments.model_dump().get("imagery_id") or "")


@dataclass(frozen=True)
class PrepareRejected:
    """前置校验未通过。`result` 是可直接回给模型/用户的结果对象。"""

    failure: PrepareFailure
    result: ToolRunResult
    error_detail: str


async def prepare_tool_call(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    user_id: str | None,
) -> PreparedTool | PrepareRejected:
    """执行前的全部校验：可用性 → 参数模型 → 资源归属。

    **任何工具执行前都必须过这一关，没有例外。** 多步链路里的每一步都要各自调用，
    不允许"第一步校验通过就整条链路放行"——中间步骤的参数是模型现编的。
    """
    tool = get_tool(tool_name)
    if tool is None or not tool.is_enabled():
        message = f"不允许调用工具：{tool_name}"
        return PrepareRejected(
            failure="tool_unavailable",
            error_detail="tool_unavailable",
            result=ToolRunResult(
                tool_context=f"工具未执行：{message}",
                error="tool_unavailable",
                metadata={"error_code": "tool_unavailable"},
            ),
        )

    try:
        validated = tool.argument_model.model_validate(arguments)
    except ValidationError as exc:
        return PrepareRejected(
            failure="invalid_arguments",
            error_detail=str(exc),
            result=ToolRunResult(
                tool_context="工具参数无效，已跳过执行。",
                error=str(exc),
                metadata={"error_code": "invalid_arguments"},
            ),
        )

    access_error = await validate_tool_access(tool_name, validated.model_dump(), user_id)
    if access_error:
        return PrepareRejected(
            failure="access_denied",
            error_detail=access_error,
            result=ToolRunResult(
                tool_context="工具访问被拒绝：当前用户无权访问该资源。",
                error=access_error,
                metadata={"error_code": access_error},
            ),
        )

    if tool_name == "segment_instances":
        from app.agent.imagery_access import get_user_imagery_metadata
        from app.agent.imagery_selection import geo_roi_mismatch, grid_resolution_m
        from app.core.settings import get_settings
        meta = await get_user_imagery_metadata(arguments.get("imagery_id", ""), user_id)
        message = None
        code = "invalid_roi"
        if meta:
            if (arguments.get("bbox_crs") or "EPSG:4326").upper() in {"EPSG:4326", "WGS84"} and geo_roi_mismatch(meta.get("bounds"), arguments.get("bbox")):
                message = "框选区域与此影像不相交；请选择覆盖选区的影像或重新框选。相同参数重复提交不会成功。"
            resolution = grid_resolution_m(meta)
            limit = get_settings().sam3_max_resolution_m
            if not message and resolution is not None and resolution > limit:
                code = "unsupported_resolution"
                message = f"当前分析网格约 {resolution:.2f} 米/像元，超过平台对 SAM3 精细目标分割设置的 {limit:g} 米适用上限。这是平台的保守使用规则，并非精度保证；粗分辨率影像不能可靠恢复建筑等目标轮廓。请使用更高分辨率影像；本次未运行推理。"
        if message:
            return PrepareRejected(failure="analysis_precondition", error_detail=code,
                result=ToolRunResult(tool_context=message, error=code, metadata={"error_code": code}))

    return PreparedTool(tool=tool, arguments=validated, user_id=user_id)


async def run_prepared_tool(prepared: PreparedTool) -> ToolRunResult:
    """执行已通过校验的工具：durable 队列登记 → staging → runner → 终态落库。

    runner 抛异常不会外泄：统一转成带 `tool_runner_exception` 的失败结果，
    让上层（模型或 trace）拿到可读信息而不是炸掉整条链路。
    """
    job_id: str | None = None
    try:
        # durable 工具队列：登记 pending→running 行（best-effort，关闭/无库则 job_id=None）。
        job_id = await begin_tool_job(
            tool_name=prepared.name,
            arguments=prepared.arguments.model_dump(),
            imagery_id=prepared.imagery_id,
            user_id=prepared.user_id,
        )
        # 执行期心跳：长任务（detect/segment、并发闸排队、minio 大影像 staging）全程刷新
        # heartbeat_at，避免被恢复 worker 误判成孤儿而重复执行。job_id=None 时为 no-op。
        async with heartbeat_tool_job(job_id):
            if prepared.imagery_id:
                # minio 后端下把影像拉到请求级临时目录供 runner/docker 读取；local 后端为 no-op。
                async with stage_imagery(prepared.imagery_id):
                    result = await prepared.tool.runner(prepared.arguments)
            else:
                result = await prepared.tool.runner(prepared.arguments)
    except Exception as exc:
        logger.exception("工具 %s 执行抛出未处理异常", prepared.name)
        result = ToolRunResult(
            tool_context="工具执行失败，已跳过该工具结果。",
            error=str(exc),
            metadata={"error_code": "tool_runner_exception"},
        )

    # 写终态（complete/failed）。job_id 为 None 时 no-op；best-effort 不抛进主路径。
    await finish_tool_job(job_id, result)
    return result

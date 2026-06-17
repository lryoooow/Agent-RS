from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, Awaitable, Callable

from app.agent.child import ToolChildAgent
from app.agent.prompting.scenarios import tool_running_label
from app.agent.types import AgentEvent, AgentTrace, RuntimeToolCall, ToolRunResult

AgentEventCallback = Callable[[AgentEvent], Awaitable[None]]

# 工具 -> 领域子 agent 的归属表（单一数据源）。
# 新增工具时只在这里登记归属，runtime 自动按领域派发。
TOOL_DOMAIN: dict[str, str] = {
    "raster_inspect": "spectral_agent",
    "calculate_ndvi": "spectral_agent",
    "calculate_spectral_index": "spectral_agent",
    "render_band_composite": "spectral_agent",
    "segment_landcover": "segmentation_agent",
    "detect_objects": "detection_agent",
    "cloud_shadow_mask": "preprocess_agent",
    "extract_water_mask": "preprocess_agent",
    "clip_reproject_raster": "preprocess_agent",
    "parse_document": "document_agent",
    "ocr_recognize": "document_agent",
}

DOMAIN_LABELS: dict[str, str] = {
    "spectral_agent": "指数分析",
    "segmentation_agent": "地物分类",
    "detection_agent": "目标检测",
    "preprocess_agent": "预处理",
    "document_agent": "文档解析",
}


DOMAIN_GUIDANCE: dict[str, str] = {
    "spectral_agent": (
        "[指数分析领域指引] 引用返回的 min/max/mean/std/nodata 等真实统计。"
        "解读边界仅供参考，非绝对判定，阈值会随传感器、地区、季节、大气校正变化；"
        "NDVI/EVI 等植被指数一般高值表示植被更旺盛，低值多为裸土/建筑/水体/云等弱植被或非植被；"
        "NDWI/MNDWI 高值倾向指示水体，NDBI 高值倾向指示建筑。"
        "不要把阈值写成绝对标准，不要编造未返回的统计。"
    ),
    "detection_agent": (
        "[目标检测领域指引] 引用返回的目标总数、各类别计数、置信度阈值；"
        "说明 DOTA 15 类模型适用边界，低于阈值的目标已被过滤；"
        "默认按 GF-2 波序 red=3, green=2, blue=1，非 GF-2 影像应显式指定 RGB 波段；"
        "不要编造未检出的类别。"
    ),
    "segmentation_agent": (
        "[地物分类领域指引] 引用返回的各类别像素数与占比；"
        "说明 LandCover.ai 类别（建筑/林地/水体/背景）模型边界；"
        "默认按 GF-2 波序 red=3, green=2, blue=1，非 GF-2 影像应显式指定 RGB 波段；"
        "不要编造未返回的类别或面积。"
    ),
    "preprocess_agent": (
        "[预处理领域指引] 只陈述本次预处理返回的真实结果（掩膜占比统计、裁剪/重投影的坐标系与输出范围等），"
        "不编造未返回的数值。云/阴影、水体等掩膜为阈值法粗筛（非精确模型），"
        "可能漏检或误判边界地物，结果用于后续分析的质量控制与范围参考；"
        "裁剪/重投影产出可下载的派生栅格，不会注册为新影像 ID，如需继续分析请重新上传。"
        "不要把粗筛掩膜当成精确量，不要编造未返回的统计或变换。"
    ),
    "document_agent": (
        "[文档解析领域指引] 基于工具返回的真实文本回答，只引用其中确实出现的内容，不编造原文/图面没有的事实。"
        "本领域有两类来源：① parse_document 取上传时已解析入库的文档全文；"
        "② ocr_recognize 对栅格影像做光学字符识别，识别影像/扫描地图/图件上的文字。"
        "无论哪种来源，若源自 PDF/扫描件/影像 OCR，文本都可能含识别误差或版面错乱，"
        "引用关键数字、日期、地名、条款时保持谨慎并提示可能的识别误差；"
        "若全文被截断或未识别到文字，明确如实告知，不要臆测未返回内容。"
    ),
}


def domain_for_tool(tool_name: str) -> str | None:
    """返回工具所属领域子 agent 名；未登记返回 None。"""
    return TOOL_DOMAIN.get(tool_name)


class DomainToolAgent:
    """领域子 agent：维护自己的局部上下文（领域名 + child_run_id），
    在外层标识"我是哪个领域专家"，再委托已验证的 ToolChildAgent 执行实际工具。
    工具执行逻辑零重写，仅在其上叠加领域级 trace 上下文。"""

    def __init__(self, domain_name: str, *, parent_run_id: str | None = None) -> None:
        self.domain_name = domain_name
        self.domain_label = DOMAIN_LABELS.get(domain_name, domain_name)
        self.parent_run_id = parent_run_id or uuid.uuid4().hex

    async def run(
        self,
        tool_call: RuntimeToolCall,
        *,
        user_id: str | None,
        trace: AgentTrace,
        on_event: AgentEventCallback | None = None,
    ) -> ToolRunResult:
        child_run_id = uuid.uuid4().hex
        event = trace.add(
            "child_agent_running",
            tool_running_label(tool_call.name),
            tool_name=tool_call.name,
            agent_name=self.domain_name,
            domain=self.domain_name,
            domain_label=self.domain_label,
            parent_run_id=self.parent_run_id,
            child_run_id=child_run_id,
            execution_kind="agent",
            dispatch_kind="tool",
        )
        if on_event:
            await on_event(event)

        # 委托给已验证的工具执行器；领域 agent 的 child_run_id 作为其 parent，
        # 形成 顶层 -> 领域 agent -> 工具执行 的上下文链。
        result = await ToolChildAgent(parent_run_id=child_run_id).run(
            tool_call,
            user_id=user_id,
            trace=trace,
            on_event=on_event,
        )
        guidance = DOMAIN_GUIDANCE.get(self.domain_name)
        if guidance and result.error is None and result.tool_context:
            return replace(result, tool_context=f"{result.tool_context}\n\n{guidance}")
        return result

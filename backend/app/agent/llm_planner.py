from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.agent.capability_registry import RegisteredCapability, list_capabilities
from app.agent.config import ResolvedAIConfig
from app.agent.request_builder import build_imagery_inventory, build_planning_context
from app.agent.types import AgentTrace
from app.core.settings import get_settings
from app.schemas.chat import ChatRequest


logger = logging.getLogger(__name__)

MAX_PLANNER_CALLS = 2


@dataclass(frozen=True)
class PlannerDecision:
    action: str
    capability: str | None = None
    arguments: dict[str, Any] | None = None
    reason: str = ""
    raw: dict[str, Any] | None = None


def capability_snapshot() -> list[RegisteredCapability]:
    return list_capabilities(available_only=True)


class LLMCapabilityPlanner:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def plan(
        self,
        *,
        client: Any,
        config: ResolvedAIConfig,
        request: ChatRequest,
        query: str,
        user_id: str | None = None,
        capabilities: list[RegisteredCapability],
        trace: AgentTrace,
        on_event,
        add_event,
    ) -> PlannerDecision:
        await add_event(
            trace,
            on_event,
            "planner_started",
            "正在规划是否需要调用能力",
            capability_count=len(capabilities),
        )
        messages = await self._build_messages(
            request,
            query=query,
            user_id=user_id,
            capabilities=capabilities,
        )
        model = self.settings.agent_planning_model.strip() or config.model
        calls_used = 0
        text = ""
        while calls_used < MAX_PLANNER_CALLS:
            calls_used += 1
            try:
                response = await self._create_completion(client, model=model, messages=messages)
            except Exception as exc:
                logger.warning("Capability planner failed: %s", exc)
                if calls_used < MAX_PLANNER_CALLS:
                    continue
                await add_event(
                    trace,
                    on_event,
                    "planner_invalid",
                    "能力规划失败，降级为直接回答",
                    error=str(exc),
                    attempts=calls_used,
                )
                return PlannerDecision(action="none", reason="planner_error")

            text = _extract_text(response).strip()
            try:
                payload = _parse_json_object(text)
            except ValueError as exc:
                if calls_used < MAX_PLANNER_CALLS:
                    messages = _repair_messages(text, str(exc))
                    continue
                await add_event(
                    trace,
                    on_event,
                    "planner_invalid",
                    "能力规划输出无效，降级为直接回答",
                    error=str(exc),
                    attempts=calls_used,
                )
                return PlannerDecision(action="none", reason="invalid_json")

            decision = PlannerDecision(
                action=str(payload.get("action") or "none"),
                capability=payload.get("capability") if isinstance(payload.get("capability"), str) else None,
                arguments=payload.get("arguments") if isinstance(payload.get("arguments"), dict) else {},
                reason=str(payload.get("reason") or ""),
                raw=payload,
            )
            await add_event(
                trace,
                on_event,
                "planner_completed",
                "能力规划已完成",
                action=decision.action,
                capability=decision.capability,
                reason=decision.reason,
                attempts=calls_used,
            )
            return decision

        await add_event(
            trace,
            on_event,
            "planner_invalid",
            "能力规划失败，降级为直接回答",
            attempts=calls_used,
        )
        return PlannerDecision(action="none", reason="planner_error")

    async def _create_completion(self, client: Any, *, model: str, messages: list[dict[str, str]]) -> Any:
        return await client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            max_tokens=self.settings.agent_planner_max_tokens,
            extra_body={"enable_thinking": False},
        )

    async def _build_messages(
        self,
        request: ChatRequest,
        *,
        query: str,
        user_id: str | None,
        capabilities: list[RegisteredCapability],
    ) -> list[dict[str, str]]:
        recent = await build_planning_context(request)
        messages = [
            {"role": "system", "content": _planner_prompt(capabilities)},
        ]
        inventory = await build_imagery_inventory(user_id)
        if inventory:
            messages.append(
                {
                    "role": "system",
                    "content": "当前用户影像清单。只能使用这里列出的 imagery_id:\n" + inventory,
                }
            )
        messages.extend(recent)
        messages.append({"role": "user", "content": query[:800]})
        return messages


def _planner_prompt(capabilities: list[RegisteredCapability]) -> str:
    capability_lines = []
    for capability in capabilities:
        schema = capability.argument_model.model_json_schema()
        capability_lines.append(
            json.dumps(
                {
                    "name": capability.name,
                    "kind": capability.kind,
                    "description": capability.description,
                    "tags": capability.tags,
                    "schema": schema,
                },
                ensure_ascii=False,
            )
        )
    return (
        "你是 Agent-RS 的能力规划器，只决定是否调用一个能力，不回答用户问题。\n"
        "只输出 JSON 对象，不输出 Markdown，不输出解释。\n"
        'JSON 格式: {"action":"none|call","capability":string|null,"arguments":object,"reason":string}\n'
        "action=call 时 capability 必须来自可用能力列表，arguments 必须符合该能力 schema。\n"
        "不要凭空编造 imagery_id；只能使用当前用户影像清单或对话上下文中可用的完整 ID。\n"
        "如果当前影像清单恰好只有一张自有影像，用户用“这张图”“刚才那张图”“上面那景”等指代词，或给出可唯一匹配的残缺/写错 imagery_id，可以使用清单里的完整 imagery_id。\n"
        "如果影像清单有多张图：当用户给出的残缺/写错 imagery_id 能在清单里唯一匹配到一张完整 ID（前缀一致或仅个别字符出入且只匹配一张），用那张的完整 ID 调用；若只用指代词没给 ID 片段、或残缺 ID 能匹配到多张、或匹配不到任何一张，则选择 none 并请用户指明影像，不要在多个候选里随意猜一张。\n"
        "如果用户显式说没有提供影像 ID、没有可用影像 ID、没有提供文档 ID，选择 none；显式否定优先于系统清单。\n"
        "不要凭空编造 document_id。判别只看一条：系统是否在上下文中注入了文档信息（如“用户已上传需要解析的文档”）或此前轮次已出现该文档。只要有这类文档证据，用户给出 document_id 要求解析/总结文档，就调用 parse_document；只有在完全没有任何文档证据时，用户口头报出的 document_id 才一律选择 none 并请用户先上传或指明文档。\n"
        "普通解释、代码、翻译、数学、写作任务选择 none。\n"
        "如果用户明确说不要调用工具、不要计算、先别处理、只解释概念或只讲原理，选择 none。\n"
        "如果用户把工具或算法用于明显不匹配的任务，选择 none，不要硬凑最接近的工具。例如：用 NDVI 检测船只、用重投影识别车辆、用 OCR 判断植被覆盖率。\n"
        "需要实时、最新、外部验证、天气、价格、官网、来源时选择 web_search。\n"
        "复合问题(同时包含多个独立检索意图，如实时天气 + 出行攻略)调用 web_search 时，"
        "用 arguments.queries 给每个意图各写一条聚焦检索词；单一意图问题只用 query 即可。\n"
        "系统当前一次只能执行一个非搜索工具；如果用户要求多个遥感工具步骤，选择第一个可独立执行的工具，后续步骤等待下一轮或工作流能力支持。\n"
        "有影像但用户只问概念或含义时仍选择 none，不要因为看到影像清单就调用工具。\n"
        "示例:\n"
        '用户: 你好 -> {"action":"none","capability":null,"arguments":{},"reason":"greeting"}\n'
        '用户: 什么是 NDVI？ -> {"action":"none","capability":null,"arguments":{},"reason":"concept_question"}\n'
        '用户: 这张图的 NDVI 是什么意思？ -> {"action":"none","capability":null,"arguments":{},"reason":"concept_question_with_imagery"}\n'
        '用户: 明天杭州有中雨吗？ -> {"action":"call","capability":"web_search","arguments":{"query":"明天杭州天气 中雨","reason":"需要实时天气"},"reason":"needs_current_weather"}\n'
        '用户: 明天上海天气怎么样？我想过去自驾游，给我一份两天一夜计划 -> {"action":"call","capability":"web_search","arguments":{"query":"明天上海天气预报","queries":["明天上海天气预报","上海周边自驾游 两天一夜 路线攻略"],"reason":"实时天气与自驾攻略两个独立意图"},"reason":"compound_weather_and_travel"}\n'
        '用户: 计算影像 94e758f38ede 的 NDVI -> {"action":"call","capability":"calculate_ndvi","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求计算 NDVI"},"reason":"ndvi_calculation"}\n'
        '用户: 检查影像 94e758f38ede 的波段和 CRS -> {"action":"call","capability":"raster_inspect","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求影像质检"},"reason":"imagery_inspection"}\n'
        '用户: 算一下影像 94e758f38ede 的 NBR -> {"action":"call","capability":"calculate_spectral_index","arguments":{"imagery_id":"94e758f38ede","index_type":"nbr","reason":"用户请求火烧迹地指数"},"reason":"spectral_index"}\n'
        '用户: 用真彩色显示影像 94e758f38ede -> {"action":"call","capability":"render_band_composite","arguments":{"imagery_id":"94e758f38ede","mode":"true_color","reason":"用户请求真彩色合成"},"reason":"band_composite"}\n'
        '用户: 检测影像 94e758f38ede 里的飞机和船只 -> {"action":"call","capability":"detect_objects","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求目标检测"},"reason":"object_detection"}\n'
        '用户: 把影像 94e758f38ede 做地物分割 -> {"action":"call","capability":"segment_landcover","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求地物分割"},"reason":"landcover_segmentation"}\n'
        '用户: (本对话此前已对影像做过地物分类) 根据刚才的分类结果帮我生成一份报告 -> {"action":"call","capability":"generate_report","arguments":{"reason":"用户请求把已有分析结果导出为报告"},"reason":"generate_report"}\n'
        '用户: (本对话还没做过任何分析) 帮我生成一份分析报告 -> {"action":"none","capability":null,"arguments":{},"reason":"no_analysis_to_report"}\n'
        '用户: 给影像 94e758f38ede 做云掩膜/去云质检 -> {"action":"call","capability":"cloud_shadow_mask","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求云阴影掩膜"},"reason":"cloud_shadow_mask"}\n'
        '用户: 提取影像 94e758f38ede 里的水体/圈出水域范围 -> {"action":"call","capability":"extract_water_mask","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求水体提取"},"reason":"extract_water_mask"}\n'
        '用户: 把影像 94e758f38ede 重投影到 EPSG:4326 / 按范围裁剪 -> {"action":"call","capability":"clip_reproject_raster","arguments":{"imagery_id":"94e758f38ede","dst_crs":"EPSG:4326","reason":"用户请求裁剪/重投影"},"reason":"clip_reproject_raster"}\n'
        '用户: 识别影像 94e758f38ede 上的文字 / 读出这张扫描地图里的注记 -> {"action":"call","capability":"ocr_recognize","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求识别影像中的文字"},"reason":"ocr_recognize"}\n'
        '用户: (系统已注入：用户已上传需要解析的文档) 总结文档 3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071 / 把整篇文档的要点列出来 -> {"action":"call","capability":"parse_document","arguments":{"document_id":"3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071","reason":"用户请求总结整篇文档"},"reason":"parse_document"}\n'
        '用户: (系统已注入：用户已上传需要解析的文档) 文档 3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071 帮我总结要点，里面图片文字不重要 -> {"action":"call","capability":"parse_document","arguments":{"document_id":"3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071","reason":"用户要总结文档全文，图片OCR非主诉求"},"reason":"parse_document_not_ocr"}\n'
        '用户: (上下文没有任何文档) 解析文档 3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071 -> {"action":"none","capability":null,"arguments":{},"reason":"no_document_evidence"}\n'
        '用户: 计算刚才那张图的 NDVI，但没有可用影像 ID -> {"action":"none","capability":null,"arguments":{},"reason":"missing_imagery_id"}\n'
        '用户: (清单有 47ab9c20f1e3、8d3f00aa1122 两张) 给 47ab9c 这张做水体掩膜（ID没记全）-> {"action":"call","capability":"extract_water_mask","arguments":{"imagery_id":"47ab9c20f1e3","reason":"残缺ID唯一匹配清单中一张"},"reason":"unique_prefix_match"}\n'
        '用户: (清单有 47ab9c20f1e3、47ab9c885566 两张) 给 47ab9c 这张做水体掩膜（ID没记全）-> {"action":"none","capability":null,"arguments":{},"reason":"ambiguous_imagery_multiple_candidates"}\n'
        "可用能力:\n"
        "detect_objects 和 segment_landcover 默认按 GF-2 波序 red=3, green=2, blue=1；非 GF-2 或用户明确说明 RGB 波序时，应显式设置 red_band/green_band/blue_band。\n"
        + "\n".join(capability_lines)
    )


def _repair_messages(raw_text: str, error: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是 JSON 修复器。只输出一个合法 JSON 对象，不输出 Markdown 或解释。\n"
                '目标格式: {"action":"none|call","capability":string|null,"arguments":object,"reason":string}'
            ),
        },
        {
            "role": "user",
            "content": (
                "下面是能力规划器的非法输出，请修复为目标 JSON 格式。\n"
                f"解析错误: {error}\n"
                f"原始输出:\n{raw_text[:2000]}"
            ),
        },
    ]


def _parse_json_object(text: str) -> dict[str, Any]:
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("missing json object")
    payload = json.loads(text[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("planner output is not an object")
    return payload


def _extract_text(response: Any) -> str:
    choices = _read(response, "choices", []) or []
    if not choices:
        return ""
    message = _read(choices[0], "message", {})
    return _read(message, "content", "") or ""


def _read(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)

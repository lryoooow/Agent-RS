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
        inventory = build_imagery_inventory(user_id)
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
        "不要猜测 imagery_id；只有当前用户影像清单或对话上下文明确出现的可用 ID 才能用于遥感工具。\n"
        "普通解释、代码、翻译、数学、写作任务选择 none。\n"
        "需要实时、最新、外部验证、天气、价格、官网、来源时选择 web_search。\n"
        "复合问题(同时包含多个独立检索意图，如实时天气 + 出行攻略)调用 web_search 时，"
        "用 arguments.queries 给每个意图各写一条聚焦检索词；单一意图问题只用 query 即可。\n"
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
        '用户: 给影像 94e758f38ede 做云掩膜/去云质检 -> {"action":"call","capability":"cloud_shadow_mask","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求云阴影掩膜"},"reason":"cloud_shadow_mask"}\n'
        '用户: 提取影像 94e758f38ede 里的水体/圈出水域范围 -> {"action":"call","capability":"extract_water_mask","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求水体提取"},"reason":"extract_water_mask"}\n'
        '用户: 把影像 94e758f38ede 重投影到 EPSG:4326 / 按范围裁剪 -> {"action":"call","capability":"clip_reproject_raster","arguments":{"imagery_id":"94e758f38ede","dst_crs":"EPSG:4326","reason":"用户请求裁剪/重投影"},"reason":"clip_reproject_raster"}\n'
        '用户: 识别影像 94e758f38ede 上的文字 / 读出这张扫描地图里的注记 -> {"action":"call","capability":"ocr_recognize","arguments":{"imagery_id":"94e758f38ede","reason":"用户请求识别影像中的文字"},"reason":"ocr_recognize"}\n'
        '用户: 总结文档 3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071 / 把整篇文档的要点列出来 -> {"action":"call","capability":"parse_document","arguments":{"document_id":"3f2a1b4c-5d6e-7f80-9a1b-2c3d4e5f6071","reason":"用户请求总结整篇文档"},"reason":"parse_document"}\n'
        '用户: 计算刚才那张图的 NDVI，但没有可用影像 ID -> {"action":"none","capability":null,"arguments":{},"reason":"missing_imagery_id"}\n'
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

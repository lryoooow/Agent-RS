from __future__ import annotations

from app.schemas.chat import ChatMessage


TOOL_FINAL_PROMPTS: dict[str, str] = {
    "web_search": "正在基于联网搜索结果生成最终回答",
    "calculate_ndvi": "正在基于 NDVI 计算结果生成回答",
    "raster_inspect": "正在基于影像质检结果生成回答",
    "calculate_spectral_index": "正在基于光谱指数计算结果生成回答",
    "render_band_composite": "正在基于波段组合结果生成回答",
    "detect_objects": "正在基于目标检测结果生成回答",
    "segment_landcover": "正在基于地物分割结果生成回答",
}


TOOL_REQUEST_LABELS: dict[str, str] = {
    "web_search": "请求调用联网搜索",
    "calculate_ndvi": "请求调用 NDVI 计算",
    "raster_inspect": "请求调用影像质检",
    "calculate_spectral_index": "请求调用光谱指数计算",
    "render_band_composite": "请求调用波段组合渲染",
    "detect_objects": "请求调用目标检测",
    "segment_landcover": "请求调用地物分割",
}


TOOL_READY_LABELS: dict[str, str] = {
    "web_search": "联网搜索结果已整理",
    "calculate_ndvi": "NDVI 计算结果已整理",
    "raster_inspect": "影像质检结果已整理",
    "calculate_spectral_index": "光谱指数结果已整理",
    "render_band_composite": "波段组合结果已整理",
    "detect_objects": "目标检测结果已整理",
    "segment_landcover": "地物分割结果已整理",
}


def latest_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content.strip()
    return ""


def tool_final_label(tool_name: str) -> str:
    return TOOL_FINAL_PROMPTS.get(tool_name, "正在基于工具结果生成最终回答")


def tool_request_label(tool_name: str) -> str:
    return TOOL_REQUEST_LABELS.get(tool_name, f"请求调用工具：{tool_name}")


def tool_ready_label(tool_name: str) -> str:
    return TOOL_READY_LABELS.get(tool_name, "工具结果已整理")

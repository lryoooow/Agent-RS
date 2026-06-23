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
    "cloud_shadow_mask": "正在基于云/阴影掩膜结果生成回答",
    "extract_water_mask": "正在基于水体掩膜结果生成回答",
    "clip_reproject_raster": "正在基于裁剪/重投影结果生成回答",
    "parse_document": "正在基于文档解析结果生成回答",
    "ocr_recognize": "正在基于影像文字识别结果生成回答",
    "generate_report": "正在基于分析报告生成回答",
}


TOOL_REQUEST_LABELS: dict[str, str] = {
    "web_search": "请求调用联网搜索",
    "calculate_ndvi": "请求调用 NDVI 计算",
    "raster_inspect": "请求调用影像质检",
    "calculate_spectral_index": "请求调用光谱指数计算",
    "render_band_composite": "请求调用波段组合渲染",
    "detect_objects": "请求调用目标检测",
    "segment_landcover": "请求调用地物分割",
    "cloud_shadow_mask": "请求调用云/阴影掩膜",
    "extract_water_mask": "请求调用水体掩膜提取",
    "clip_reproject_raster": "请求调用裁剪/重投影",
    "parse_document": "请求调用文档解析",
    "ocr_recognize": "请求调用影像文字识别",
    "generate_report": "请求生成分析报告",
}


TOOL_READY_LABELS: dict[str, str] = {
    "web_search": "联网搜索结果已整理",
    "calculate_ndvi": "NDVI 计算结果已整理",
    "raster_inspect": "影像质检结果已整理",
    "calculate_spectral_index": "光谱指数结果已整理",
    "render_band_composite": "波段组合结果已整理",
    "detect_objects": "目标检测结果已整理",
    "segment_landcover": "地物分割结果已整理",
    "cloud_shadow_mask": "云/阴影掩膜结果已整理",
    "extract_water_mask": "水体掩膜结果已整理",
    "clip_reproject_raster": "裁剪/重投影结果已整理",
    "parse_document": "文档解析结果已整理",
    "ocr_recognize": "影像文字识别结果已整理",
    "generate_report": "分析报告已生成",
}


# 执行阶段（child_agent_running）展示的"正在做什么"标签：用具体能力名替代统一的"正在执行工具"。
# 覆盖 domain_agents.TOOL_DOMAIN 登记的全部工具 + web_search；未登记走兜底。
TOOL_RUNNING_LABELS: dict[str, str] = {
    "web_search": "正在联网搜索",
    "calculate_ndvi": "正在计算 NDVI",
    "calculate_spectral_index": "正在计算光谱指数",
    "render_band_composite": "正在渲染波段组合",
    "raster_inspect": "正在进行影像质检",
    "segment_landcover": "正在进行地物分类",
    "detect_objects": "正在进行目标检测",
    "cloud_shadow_mask": "正在生成云/阴影掩膜",
    "extract_water_mask": "正在提取水体掩膜",
    "clip_reproject_raster": "正在裁剪/重投影影像",
    "parse_document": "正在解析文档",
    "ocr_recognize": "正在识别影像文字",
    "generate_report": "正在生成分析报告",
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


def tool_running_label(tool_name: str) -> str:
    return TOOL_RUNNING_LABELS.get(tool_name, f"正在执行工具：{tool_name}")

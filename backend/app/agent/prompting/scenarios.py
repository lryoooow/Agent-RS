from __future__ import annotations

from app.schemas.chat import ChatMessage


WEB_PLANNING_PROMPT = """你是搜索决策器，只判断是否需要联网搜索。
职责：需要最新事实、实时数据、新闻、价格、法规、外部验证时回答 YES；普通解释、写作、代码、数学、已有上下文可回答时回答 NO。
边界：只输出 YES 或 NO，不解释。
示例：
用户：今天英伟达股价是多少？ -> YES
用户：解释一下 Transformer 注意力机制。 -> NO
用户：核实这个库最新版本。 -> YES"""


TOOL_FINAL_PROMPTS: dict[str, str] = {
    "web_search": "正在基于联网搜索结果生成最终回答",
    "calculate_ndvi": "正在基于 NDVI 计算结果生成回答",
    "raster_inspect": "正在基于影像质检结果生成回答",
    "calculate_spectral_index": "正在基于光谱指数计算结果生成回答",
    "render_band_composite": "正在基于波段组合结果生成回答",
}


TOOL_REQUEST_LABELS: dict[str, str] = {
    "web_search": "请求调用联网搜索",
    "calculate_ndvi": "请求调用 NDVI 计算",
    "raster_inspect": "请求调用影像质检",
    "calculate_spectral_index": "请求调用光谱指数计算",
    "render_band_composite": "请求调用波段组合渲染",
}


TOOL_READY_LABELS: dict[str, str] = {
    "web_search": "联网搜索结果已整理",
    "calculate_ndvi": "NDVI 计算结果已整理",
    "raster_inspect": "影像质检结果已整理",
    "calculate_spectral_index": "光谱指数结果已整理",
    "render_band_composite": "波段组合结果已整理",
}


NDVI_CALCULATION_TERMS = (
    "计算",
    "算一下",
    "生成",
    "分析",
    "处理",
    "跑",
    "执行",
    "calculate",
    "compute",
    "run",
)

NDVI_EXPLANATION_TERMS = (
    "什么是",
    "解释",
    "介绍",
    "原理",
    "含义",
    "怎么理解",
    "what is",
    "explain",
    "meaning",
)

IMAGERY_TERMS = (
    "影像",
    "遥感",
    "高分",
    "tif",
    "tiff",
    "geotiff",
    "imagery",
    "image",
    "raster",
)


def latest_user_text(messages: list[ChatMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user":
            return message.content.strip()
    return ""


def wants_ndvi_calculation(text: str) -> bool:
    lowered = text.lower()
    if "ndvi" not in lowered and "植被指数" not in text:
        return False
    if any(term in lowered for term in NDVI_EXPLANATION_TERMS):
        return False
    return any(term in lowered for term in NDVI_CALCULATION_TERMS) or any(
        term in lowered for term in IMAGERY_TERMS
    )


def wants_imagery_context(text: str) -> bool:
    lowered = text.lower()
    return wants_ndvi_calculation(text) or wants_imagery_tool(text) or any(term in lowered for term in IMAGERY_TERMS)


def wants_imagery_tool(text: str) -> bool:
    lowered = text.lower()
    keywords = (
        "检查影像",
        "影像信息",
        "波段信息",
        "分辨率",
        "metadata",
        "ndwi",
        "mndwi",
        "ndbi",
        "evi",
        "savi",
        "水体指数",
        "建筑指数",
        "真彩色",
        "假彩色",
        "波段组合",
        "432组合",
        "rgb",
        "composite",
    )
    return any(keyword in lowered for keyword in keywords)


def tool_final_label(tool_name: str) -> str:
    return TOOL_FINAL_PROMPTS.get(tool_name, "正在基于工具结果生成最终回答")


def tool_request_label(tool_name: str) -> str:
    return TOOL_REQUEST_LABELS.get(tool_name, f"请求调用工具：{tool_name}")


def tool_ready_label(tool_name: str) -> str:
    return TOOL_READY_LABELS.get(tool_name, "工具结果已整理")

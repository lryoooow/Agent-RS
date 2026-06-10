from pydantic import BaseModel, Field


class WaterMaskArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的ID")
    green_band: int = Field(default=2, ge=1, description="绿光波段号（GF-2默认2）")
    nir_band: int = Field(default=4, ge=1, description="近红外波段号（GF-2默认4）")
    reason: str = Field(default="用户请求水体提取", description="计算原因")


WATER_MASK_TOOL = {
    "type": "function",
    "function": {
        "name": "extract_water_mask",
        "description": (
            "对上传的多光谱卫星影像做水体掩膜（基于 NDWI 的阈值法粗筛，用于水体范围提取、"
            "水域变化、洪涝/水资源监测的前置分析）。当用户要求提取水体、识别河流湖泊水库、"
            "圈定水域范围或做水体专题时调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {
                    "type": "string",
                    "description": "已上传影像的ID",
                },
                "green_band": {
                    "type": "integer",
                    "default": 2,
                    "description": "绿光波段号（GF-2默认Band2=Green）",
                },
                "nir_band": {
                    "type": "integer",
                    "default": 4,
                    "description": "近红外波段号（GF-2默认Band4=NIR）",
                },
                "reason": {
                    "type": "string",
                    "description": "计算原因说明",
                },
            },
            "required": ["imagery_id"],
            "additionalProperties": False,
        },
    },
}

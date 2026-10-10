from pydantic import BaseModel, Field


class WaterMaskArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的ID")
    green_band: int = Field(default=2, ge=1, description="绿光波段号（省略时按影像真实角色解析；禁止套用默认波序）")
    nir_band: int = Field(default=4, ge=1, description="近红外波段号（省略时按影像真实角色解析；禁止套用默认波序）")
    # NDWI 物理阈值（McFeeters 1996：水体 NDWI > 0）。历史 bug：曾用 85 分位
    # 相对阈值，等于把水体占比封顶在 ~15%（工作单 A1）。
    threshold: float = Field(default=0.0, ge=-1.0, le=1.0, description="NDWI 水体判定阈值，默认 0.0")
    reason: str = Field(default="用户请求水体提取", description="计算原因")


WATER_MASK_TOOL_NAME = "extract_water_mask"
WATER_MASK_TOOL_DESCRIPTION = (
    "对上传的多光谱卫星影像做水体掩膜（基于 NDWI 的阈值法粗筛，用于水体范围提取、"
    "水域变化、洪涝/水资源监测的前置分析）。当用户要求提取水体、识别河流湖泊水库、"
    "圈定水域范围或做水体专题时调用此工具。"
)

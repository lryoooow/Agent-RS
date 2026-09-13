from pydantic import BaseModel, Field


class NDVIArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的ID")
    red_band: int = Field(default=3, ge=1, description="红光波段号（GF-2默认3）")
    nir_band: int = Field(default=4, ge=1, description="近红外波段号（GF-2默认4）")
    reason: str = Field(default="用户请求计算NDVI", description="计算原因")


NDVI_TOOL_NAME = "calculate_ndvi"
NDVI_TOOL_DESCRIPTION = (
    "从上传的多光谱卫星影像计算NDVI(归一化植被指数)。"
    "当用户要求计算NDVI、植被指数、分析植被覆盖时调用此工具。"
)

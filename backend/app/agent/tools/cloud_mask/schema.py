from pydantic import BaseModel, Field


class CloudMaskArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的ID")
    red_band: int = Field(default=3, ge=1, description="红光波段号（GF-2默认3）")
    green_band: int = Field(default=2, ge=1, description="绿光波段号（GF-2默认2）")
    blue_band: int = Field(default=1, ge=1, description="蓝光波段号（GF-2默认1）")
    nir_band: int = Field(default=4, ge=1, description="近红外波段号（GF-2默认4）")
    reason: str = Field(default="用户请求云/阴影掩膜", description="计算原因")


CLOUD_MASK_TOOL_NAME = "cloud_shadow_mask"
CLOUD_MASK_TOOL_DESCRIPTION = (
    "对上传的多光谱卫星影像做云/阴影/无效像素掩膜（阈值法粗筛，用于后续指数、"
    "分类、变化检测的质量控制）。当用户要求去云、云检测、云阴影掩膜、数据质量"
    "检查或为后续分析做预处理时调用此工具。"
)

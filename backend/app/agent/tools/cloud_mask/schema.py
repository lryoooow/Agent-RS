from typing import Literal

from pydantic import BaseModel, Field


class CloudMaskArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的ID")
    method: Literal["quality", "heuristic"] = Field(
        default="quality", description="默认解码影像附带的传感器QA/SCL产品；仅用户明确要求未验证的疑似亮暗区粗筛时使用heuristic。缺QA不得自动降级。",
    )
    red_band: int = Field(default=3, ge=1, description="仅heuristic使用的红光波段号；未显式指定时从影像角色解析")
    green_band: int = Field(default=2, ge=1, description="仅heuristic使用的绿光波段号；未显式指定时从影像角色解析")
    blue_band: int = Field(default=1, ge=1, description="仅heuristic使用的蓝光波段号；未显式指定时从影像角色解析")
    nir_band: int = Field(default=4, ge=1, description="仅heuristic使用的近红外波段号；未显式指定时从影像角色解析")
    reason: str = Field(default="用户请求云/阴影质量产品", description="计算原因")


CLOUD_MASK_TOOL_NAME = "cloud_shadow_mask"
CLOUD_MASK_TOOL_DESCRIPTION = (
    "解码当前影像附带的Sentinel-2 SCL或Landsat C2 QA_PIXEL质量产品，输出产品标记的云、"
    "云影、未知、雪冰与地形阴影统计。缺少可信QA时明确不可用，不能根据四波段亮暗宣称云量或晴空。"
    "质量产品标记也不代表精确实测云量或可分析性保证。仅用户明确要求疑似亮暗区粗筛时才设置"
    "method=heuristic，该未验证结果不得用于定量云量、自动去云或自动质量验收。"
)

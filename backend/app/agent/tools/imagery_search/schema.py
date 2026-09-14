from pydantic import BaseModel, Field
from typing import Literal


class ImagerySearchArguments(BaseModel):
    model_config = {"extra": "forbid"}

    bbox: list[float] | None = Field(
        default=None,
        min_length=4,
        max_length=4,
        description="检索范围 [west, south, east, north]（EPSG:4326）；与 place 二选一",
    )
    place: str | None = Field(
        default=None,
        max_length=200,
        description="地名（如“深圳南山”），服务端解析为检索范围；与 bbox 二选一",
    )
    start_date: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="起始日期 YYYY-MM-DD（含）"
    )
    end_date: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="结束日期 YYYY-MM-DD（含）"
    )
    cloud_max: float | None = Field(
        default=None, ge=0, le=100, description="云量上限（%），留空不限"
    )
    source: Literal["auto", "sentinel2", "landsat"] = Field(
        default="auto",
        description="数据源：auto=Sentinel-2(10m)+Landsat(30m) 并查；sentinel2/landsat 单查",
    )
    limit: int = Field(default=5, ge=1, le=10, description="返回场景数上限")
    reason: str = Field(default="用户请求检索卫星影像", description="检索原因")


IMAGERY_SEARCH_TOOL_NAME = "search_imagery"
IMAGERY_SEARCH_TOOL_DESCRIPTION = (
    "检索免账号公开卫星影像档案（Sentinel-2 地表反射率 10m / Landsat 8-9 30m）。"
    "当用户想找、看、下载某区域某时段的卫星影像，或需要为新区域取图做分析时调用。"
    "返回场景列表（日期/云量/分辨率），结果会以卡片呈现给用户供预览与下载；"
    "要把某景导入平台做分析，用 fetch_scene 传场景 key。没查到时建议放宽时间或云量。"
)

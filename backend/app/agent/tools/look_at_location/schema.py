from pydantic import BaseModel, Field


class LookAtLocationArguments(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1, max_length=200, description="要定位的地名")
    zoom: int | None = Field(default=None, ge=0, le=20, description="可选缩放级别 0-20")


LOOK_AT_LOCATION_TOOL_NAME = "look_at_location"
LOOK_AT_LOCATION_TOOL_DESCRIPTION = (
    "定位到用户提到的地名并让地图跳转过去。当用户想查看/前往某个地点"
    "（如“带我去深圳南山”“看一下长江流域”“定位到北京天安门”）时调用。"
    "返回该地中心坐标与可选区域边界。此工具只移动地图视角，不分析影像。"
)

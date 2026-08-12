from pydantic import BaseModel, Field


class LookAtLocationArguments(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1, max_length=200, description="要定位的地名")
    zoom: int | None = Field(default=None, ge=0, le=20, description="可选缩放级别 0-20")


LOOK_AT_LOCATION_TOOL = {
    "type": "function",
    "function": {
        "name": "look_at_location",
        "description": (
            "定位到用户提到的地名并让地图跳转过去。当用户想查看/前往某个地点"
            "（如“带我去深圳南山”“看一下长江流域”“定位到北京天安门”）时调用。"
            "返回该地中心坐标与可选区域边界。此工具只移动地图视角，不分析影像。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "地名，如“深圳南山”“长江流域”“北京”"},
                "zoom": {
                    "type": "integer",
                    "description": "可选缩放级别 0-20，留空按区域大小自动",
                    "minimum": 0,
                    "maximum": 20,
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

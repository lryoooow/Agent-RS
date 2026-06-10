from pydantic import BaseModel, Field


class RasterInspectArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的 ID")
    reason: str = Field(default="用户请求检查影像", description="检查原因")


RASTER_INSPECT_TOOL = {
    "type": "function",
    "function": {
        "name": "raster_inspect",
        "description": "检查已上传遥感影像的元数据、波段统计和指数计算能力。",
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {"type": "string", "description": "已上传影像的 ID"},
                "reason": {"type": "string", "description": "检查原因说明"},
            },
            "required": ["imagery_id"],
            "additionalProperties": False,
        },
    },
}

from pydantic import BaseModel, Field


class RasterInspectArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的 ID")
    reason: str = Field(default="用户请求检查影像", description="检查原因")


RASTER_INSPECT_TOOL_NAME = "raster_inspect"
RASTER_INSPECT_TOOL_DESCRIPTION = "检查已上传遥感影像的元数据、波段统计和指数计算能力。"

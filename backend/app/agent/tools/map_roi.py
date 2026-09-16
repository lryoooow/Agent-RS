"""Expose the displayed satellite map as a user-owned, georeferenced RGB image."""
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.types import ToolRunResult
from app.auth import peek_current_user_id
from app.schemas.chat import AnalysisROI
from app.services.map_roi import MapROIError, import_map_roi


class MapROIArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    bbox: tuple[float, float, float, float] = Field(description="当前地图框选范围 [西, 南, 东, 北]，WGS84 经纬度")

    @model_validator(mode="after")
    def validate_bbox(self):
        AnalysisROI(kind="geo", bbox=self.bbox)
        return self


async def run_map_roi(args: MapROIArguments) -> ToolRunResult:
    try:
        imagery_id, meta = await import_map_roi(args.bbox, user_id=peek_current_user_id())
    except MapROIError as exc:
        return ToolRunResult(tool_context=str(exc), error="map_image_unavailable")
    return ToolRunResult(
        tool_context=(f"当前地图选区影像已就绪，imagery_id={imagery_id}，RGB 波段为 1/2/3，4 为 Alpha。"
                      "继续执行用户要求的适用分析，无需再次要求用户上传、搜索或确认影像。"
                      "来源为 Esri 卫星底图显示影像；无 NIR/SWIR，不能计算依赖这些波段的指数；"
                      "拍摄日期与原始传感器分辨率未知，采样像元尺寸不代表原始影像分辨率。"),
        result_count=1,
        geospatial_result={"type": "preview", "imagery_id": imagery_id,
                           "result_url": meta["preview_url"], "bounds": meta["bounds"]},
        metadata={"band_roles": {"red": 1, "green": 2, "blue": 3}},
    )

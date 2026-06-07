from pydantic import BaseModel, Field, model_validator


class SegmentArguments(BaseModel):
    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的 ID")
    red_band: int = Field(default=1, ge=1)
    green_band: int = Field(default=2, ge=1)
    blue_band: int = Field(default=3, ge=1)
    reason: str = Field(default="用户请求遥感地物语义分割", description="分割原因")

    @model_validator(mode="after")
    def distinct_bands(self) -> "SegmentArguments":
        bands = [self.red_band, self.green_band, self.blue_band]
        if len(set(bands)) != len(bands):
            raise ValueError("RGB 三个波段不能重复")
        return self


SEGMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "segment_landcover",
        "description": "遥感地物语义分割（U-Net / LandCover.ai，地物类别：建筑、林地、水体、背景），输出按像素分类的彩色掩膜图层。",
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {"type": "string", "description": "已上传影像的 ID"},
                "red_band": {"type": "integer", "default": 1},
                "green_band": {"type": "integer", "default": 2},
                "blue_band": {"type": "integer", "default": 3},
                "reason": {"type": "string", "description": "分割原因说明"},
            },
            "required": ["imagery_id"],
            "additionalProperties": False,
        },
    },
}

from pydantic import BaseModel, Field, model_validator


class SegmentArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的 ID")
    red_band: int = Field(default=3, ge=1)
    green_band: int = Field(default=2, ge=1)
    blue_band: int = Field(default=1, ge=1)
    bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="可选地理框 [left,bottom,right,top]；框选请求由平台可信上下文自动注入",
    )
    bbox_crs: str | None = Field(default=None, description="bbox 坐标系，通常 EPSG:4326")
    pixel_bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="可选相对像素框 [x0,y0,x1,y1]，范围 0..1，左上角为原点",
    )
    reason: str = Field(default="用户请求遥感地物语义分割", description="分割原因")

    @model_validator(mode="after")
    def distinct_bands(self) -> "SegmentArguments":
        bands = [self.red_band, self.green_band, self.blue_band]
        if len(set(bands)) != len(bands):
            raise ValueError("RGB 三个波段不能重复")
        if self.bbox is not None and self.pixel_bbox is not None:
            raise ValueError("bbox 与 pixel_bbox 只能提供一个")
        for name, box in (("bbox", self.bbox), ("pixel_bbox", self.pixel_bbox)):
            if box is None:
                continue
            x0, y0, x1, y1 = box
            if not (x0 < x1 and y0 < y1):
                raise ValueError(f"{name} 必须具有正面积")
        if self.pixel_bbox is not None and not all(0 <= v <= 1 for v in self.pixel_bbox):
            raise ValueError("pixel_bbox 必须位于 0..1")
        if self.bbox is not None and not (self.bbox_crs or "").strip():
            raise ValueError("bbox 必须同时提供 bbox_crs")
        return self


SEGMENT_TOOL = {
    "type": "function",
    "function": {
        "name": "segment_landcover",
        "description": "遥感地物语义分割（U-Net / LandCover.ai，地物类别：建筑、林地、水体、背景）。支持平台框选 ROI；框选存在时仅分类选区并输出该选区的彩色掩膜图层。",
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {"type": "string", "description": "已上传影像的 ID"},
                "red_band": {"type": "integer", "default": 3},
                "green_band": {"type": "integer", "default": 2},
                "blue_band": {"type": "integer", "default": 1},
                "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "bbox_crs": {"type": "string", "description": "bbox 的坐标系"},
                "pixel_bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "reason": {"type": "string", "description": "分割原因说明"},
            },
            "required": ["imagery_id"],
            "additionalProperties": False,
        },
    },
}

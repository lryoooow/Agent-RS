from pydantic import BaseModel, Field, model_validator


class OcrArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的ID")
    red_band: int = Field(
        default=1,
        ge=1,
        description="红光波段号（OCR 采用自然 RGB 序，默认 band1=R；GF-2 影像请显式设为 3）",
    )
    green_band: int = Field(
        default=2,
        ge=1,
        description="绿光波段号（OCR 采用自然 RGB 序，默认 band2=G；GF-2 影像请显式设为 2）",
    )
    blue_band: int = Field(
        default=3,
        ge=1,
        description="蓝光波段号（OCR 采用自然 RGB 序，默认 band3=B；GF-2 影像请显式设为 1）",
    )
    grayscale: bool = Field(
        default=False, description="是否按单波段灰度识别（扫描件/单波段图建议开启）"
    )
    max_dimension: int = Field(
        default=2048, ge=256, le=8192, description="识别前最长边缩放上限（像素）"
    )
    min_confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="文本块置信度过滤阈值 0-1"
    )
    reason: str = Field(default="用户请求识别影像中的文字", description="识别原因")

    @model_validator(mode="after")
    def _distinct_rgb_bands(self) -> "OcrArguments":
        # 灰度模式只用 red_band，不校验三波段互异；RGB 模式要求三波段不重复。
        if not self.grayscale:
            bands = [self.red_band, self.green_band, self.blue_band]
            if len(set(bands)) != len(bands):
                raise ValueError("RGB 三个波段不能重复")
        return self


OCR_TOOL = {
    "type": "function",
    "function": {
        "name": "ocr_recognize",
        "description": (
            "遥感影像 OCR 光学字符识别（RapidOCR / PP-OCRv4 引擎，中英文）。"
            "识别卫星图、航拍图、扫描地图中的文字内容（地名标注、建筑标签、路牌文字、图面注记等）。"
            "适用场景：① 扫描的纸质地图 ② 含文字注记的遥感图件 ③ 卫星图上的地名/建筑物名称。"
            "不适用：纯地物影像（农田/森林/水体）通常无可识别文字，应使用地物分类或目标检测工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {"type": "string", "description": "已上传影像的ID"},
                "red_band": {
                    "type": "integer",
                    "default": 1,
                    "description": "红光波段号（OCR 采用自然 RGB 序，默认 band1=R；GF-2 影像请显式设为 3）",
                },
                "green_band": {
                    "type": "integer",
                    "default": 2,
                    "description": "绿光波段号（OCR 采用自然 RGB 序，默认 band2=G；GF-2 影像请显式设为 2）",
                },
                "blue_band": {
                    "type": "integer",
                    "default": 3,
                    "description": "蓝光波段号（OCR 采用自然 RGB 序，默认 band3=B；GF-2 影像请显式设为 1）",
                },
                "grayscale": {
                    "type": "boolean",
                    "default": False,
                    "description": "单波段/扫描件按灰度识别",
                },
                "max_dimension": {
                    "type": "integer",
                    "default": 2048,
                    "description": "识别前最长边缩放上限",
                },
                "min_confidence": {
                    "type": "number",
                    "default": 0.0,
                    "description": "文本块置信度过滤阈值 0-1",
                },
                "reason": {"type": "string", "description": "识别原因说明"},
            },
            "required": ["imagery_id"],
            "additionalProperties": False,
        },
    },
}

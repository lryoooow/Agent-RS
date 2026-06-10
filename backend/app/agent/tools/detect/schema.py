from pydantic import BaseModel, Field, model_validator


class DetectArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的 ID")
    red_band: int = Field(default=3, ge=1)
    green_band: int = Field(default=2, ge=1)
    blue_band: int = Field(default=1, ge=1)
    score_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="用户请求遥感目标检测", description="检测原因")

    @model_validator(mode="after")
    def distinct_bands(self) -> "DetectArguments":
        bands = [self.red_band, self.green_band, self.blue_band]
        if len(set(bands)) != len(bands):
            raise ValueError("RGB 三个波段不能重复")
        return self


DETECT_TOOL = {
    "type": "function",
    "function": {
        "name": "detect_objects",
        "description": "遥感目标检测（PP-YOLOE-R，DOTA 15 类：飞机、舰船、车辆、储油罐、港口、桥梁、各类运动场等），输出旋转框叠加图层。",
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {"type": "string", "description": "已上传影像的 ID"},
                "red_band": {"type": "integer", "default": 3},
                "green_band": {"type": "integer", "default": 2},
                "blue_band": {"type": "integer", "default": 1},
                "score_threshold": {"type": "number", "default": 0.5, "description": "置信度阈值 0-1"},
                "reason": {"type": "string", "description": "检测原因说明"},
            },
            "required": ["imagery_id"],
            "additionalProperties": False,
        },
    },
}

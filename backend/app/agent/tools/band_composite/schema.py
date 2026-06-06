from typing import Literal

from pydantic import BaseModel, Field, model_validator


CompositeMode = Literal["true_color", "false_color", "custom"]


class BandCompositeArguments(BaseModel):
    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的 ID")
    mode: CompositeMode = Field(description="波段组合模式")
    bands: list[int] | None = Field(default=None, description="custom 模式下的 RGB 波段")
    reason: str = Field(default="用户请求生成波段组合", description="生成原因")

    @model_validator(mode="after")
    def validate_bands(self) -> "BandCompositeArguments":
        if self.mode == "custom":
            if self.bands is None or len(self.bands) != 3:
                raise ValueError("custom 模式必须提供 3 个波段")
            if any(band < 1 for band in self.bands):
                raise ValueError("波段索引必须从 1 开始")
        elif self.bands is not None:
            raise ValueError("非 custom 模式不应提供 bands")
        return self


BAND_COMPOSITE_TOOL = {
    "type": "function",
    "function": {
        "name": "render_band_composite",
        "description": "生成遥感影像真彩色、假彩色或自定义 RGB 波段组合预览。",
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {"type": "string", "description": "已上传影像的 ID"},
                "mode": {"type": "string", "enum": ["true_color", "false_color", "custom"]},
                "bands": {"type": "array", "items": {"type": "integer"}, "description": "custom 模式 RGB 波段"},
                "reason": {"type": "string", "description": "生成原因说明"},
            },
            "required": ["imagery_id", "mode"],
            "additionalProperties": False,
        },
    },
}

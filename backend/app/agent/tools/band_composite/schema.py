from typing import Literal

from pydantic import BaseModel, Field, model_validator


CompositeMode = Literal["true_color", "false_color", "custom"]


def required_bands_for_composite(mode: str, bands: list[int] | None, roles: dict[str, int] | None = None) -> dict[str, int]:
    roles = roles or {}
    if mode == "true_color":
        names = ("red", "green", "blue")
        if not all(name in roles for name in names):
            raise ValueError("未确定完整 RGB 波段映射，请提供原始波段定义或明确的 custom 波段组合。")
        return {name: roles[name] for name in names}
    if mode == "false_color":
        names = ("nir", "red", "green")
        if not all(name in roles for name in names):
            raise ValueError("假彩色需要已确认的近红外、红、绿波段；不能把 Alpha 当作近红外。")
        return {name: roles[name] for name in names}
    if bands is None:
        raise ValueError("custom mode requires bands")
    return {"channel_r": bands[0], "channel_g": bands[1], "channel_b": bands[2]}


class BandCompositeArguments(BaseModel):
    model_config = {"extra": "forbid"}

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


BAND_COMPOSITE_TOOL_NAME = "render_band_composite"
BAND_COMPOSITE_TOOL_DESCRIPTION = "生成遥感影像真彩色、假彩色或自定义 RGB 波段组合预览。"

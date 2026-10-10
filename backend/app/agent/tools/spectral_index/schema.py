from typing import Literal

from pydantic import BaseModel, Field, model_validator


IndexType = Literal["ndwi", "mndwi", "ndbi", "evi", "savi", "gndvi", "ndmi", "nbr", "msavi", "bsi"]

REQUIRED_BAND_NAMES: dict[str, tuple[str, ...]] = {
    "ndwi": ("green", "nir"),
    "mndwi": ("green", "swir1"),
    "ndbi": ("nir", "swir1"),
    "evi": ("blue", "red", "nir"),
    "savi": ("red", "nir"),
    "gndvi": ("green", "nir"),
    "ndmi": ("nir", "swir1"),
    "nbr": ("nir", "swir2"),
    "msavi": ("red", "nir"),
    "bsi": ("blue", "red", "nir", "swir1"),
}


def required_bands_for(
    index_type: str,
    *,
    blue_band: int,
    green_band: int,
    red_band: int,
    nir_band: int,
    swir_band: int = 5,
    swir1_band: int | None = None,
    swir2_band: int | None = None,
) -> dict[str, int]:
    band_values = {
        "blue": blue_band,
        "green": green_band,
        "red": red_band,
        "nir": nir_band,
        "swir1": swir1_band if swir1_band is not None else swir_band,
        "swir2": swir2_band if swir2_band is not None else swir_band,
    }
    return {name: band_values[name] for name in REQUIRED_BAND_NAMES[index_type]}


class SpectralIndexArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的 ID")
    index_type: IndexType = Field(description="要计算的光谱指数")
    blue_band: int = Field(default=1, ge=1, description="蓝光波段号（省略时按影像真实角色解析；禁止套用默认波序）")
    green_band: int = Field(default=2, ge=1, description="绿光波段号（省略时按影像真实角色解析；禁止套用默认波序）")
    red_band: int = Field(default=3, ge=1, description="红光波段号（省略时按影像真实角色解析；禁止套用默认波序）")
    nir_band: int = Field(default=4, ge=1, description="近红外波段号（省略时按影像真实角色解析；禁止套用默认波序）")
    swir_band: int = Field(default=5, ge=1, description="兼容旧参数；只有已知本指数需要的 SWIR1/SWIR2 角色时可使用，不能猜波长")
    swir1_band: int | None = Field(default=None, ge=1, description="约1.6微米短波红外1波段；省略时按真实元数据解析")
    swir2_band: int | None = Field(default=None, ge=1, description="约2.2微米短波红外2波段；NBR需要此波段；省略时按元数据解析")
    reason: str = Field(default="用户请求计算光谱指数", description="计算原因")

    @model_validator(mode="after")
    def distinct_required_bands(self) -> "SpectralIndexArguments":
        required = required_bands_for(
            self.index_type,
            blue_band=self.blue_band,
            green_band=self.green_band,
            red_band=self.red_band,
            nir_band=self.nir_band,
            swir_band=self.swir_band,
            swir1_band=self.swir1_band,
            swir2_band=self.swir2_band,
        )
        explicit_values = [value for role, value in required.items()
                           if (role + "_band" in self.model_fields_set and getattr(self, role + "_band") is not None)
                           or (role in {"swir1", "swir2"} and "swir_band" in self.model_fields_set)]
        if len(set(explicit_values)) != len(explicit_values):
            raise ValueError("光谱指数所需波段不能重复")
        return self


SPECTRAL_INDEX_TOOL_NAME = "calculate_spectral_index"
SPECTRAL_INDEX_TOOL_DESCRIPTION = (
    "计算 NDWI、MNDWI、NDBI、EVI、SAVI、GNDVI、NDMI、NBR、MSAVI、BSI 等遥感光谱指数。"
)

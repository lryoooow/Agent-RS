from typing import Literal

from pydantic import BaseModel, Field, model_validator


IndexType = Literal["ndwi", "mndwi", "ndbi", "evi", "savi", "gndvi", "ndmi", "nbr", "msavi", "bsi"]

REQUIRED_BAND_NAMES: dict[str, tuple[str, ...]] = {
    "ndwi": ("green", "nir"),
    "mndwi": ("green", "swir"),
    "ndbi": ("nir", "swir"),
    "evi": ("blue", "red", "nir"),
    "savi": ("red", "nir"),
    "gndvi": ("green", "nir"),
    "ndmi": ("nir", "swir"),
    "nbr": ("nir", "swir"),
    "msavi": ("red", "nir"),
    "bsi": ("blue", "red", "nir", "swir"),
}


def required_bands_for(
    index_type: str,
    *,
    blue_band: int,
    green_band: int,
    red_band: int,
    nir_band: int,
    swir_band: int,
) -> dict[str, int]:
    band_values = {
        "blue": blue_band,
        "green": green_band,
        "red": red_band,
        "nir": nir_band,
        "swir": swir_band,
    }
    return {name: band_values[name] for name in REQUIRED_BAND_NAMES[index_type]}


class SpectralIndexArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的 ID")
    index_type: IndexType = Field(description="要计算的光谱指数")
    blue_band: int = Field(default=1, ge=1, description="蓝光波段号（GF-2默认1）")
    green_band: int = Field(default=2, ge=1, description="绿光波段号（GF-2默认2）")
    red_band: int = Field(default=3, ge=1, description="红光波段号（GF-2默认3）")
    nir_band: int = Field(default=4, ge=1, description="近红外波段号（GF-2默认4）")
    swir_band: int = Field(default=5, ge=1, description="短波红外波段号（GF-2默认5）")
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
        )
        if len(set(required.values())) != len(required):
            raise ValueError("光谱指数所需波段不能重复")
        return self


SPECTRAL_INDEX_TOOL_NAME = "calculate_spectral_index"
SPECTRAL_INDEX_TOOL_DESCRIPTION = (
    "计算 NDWI、MNDWI、NDBI、EVI、SAVI、GNDVI、NDMI、NBR、MSAVI、BSI 等遥感光谱指数。"
)

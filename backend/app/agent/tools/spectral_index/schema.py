from typing import Literal

from pydantic import BaseModel, Field, model_validator


IndexType = Literal["ndwi", "mndwi", "ndbi", "evi", "savi", "gndvi", "ndmi", "nbr", "msavi", "bsi"]


class SpectralIndexArguments(BaseModel):
    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的 ID")
    index_type: IndexType = Field(description="要计算的光谱指数")
    blue_band: int = Field(default=1, ge=1)
    green_band: int = Field(default=2, ge=1)
    red_band: int = Field(default=3, ge=1)
    nir_band: int = Field(default=4, ge=1)
    swir_band: int = Field(default=5, ge=1)
    reason: str = Field(default="用户请求计算光谱指数", description="计算原因")

    @model_validator(mode="after")
    def distinct_required_bands(self) -> "SpectralIndexArguments":
        required = {
            "ndwi": [self.green_band, self.nir_band],
            "mndwi": [self.green_band, self.swir_band],
            "ndbi": [self.nir_band, self.swir_band],
            "evi": [self.blue_band, self.red_band, self.nir_band],
            "savi": [self.red_band, self.nir_band],
            "gndvi": [self.green_band, self.nir_band],
            "ndmi": [self.nir_band, self.swir_band],
            "nbr": [self.nir_band, self.swir_band],
            "msavi": [self.red_band, self.nir_band],
            "bsi": [self.blue_band, self.red_band, self.nir_band, self.swir_band],
        }[self.index_type]
        if len(set(required)) != len(required):
            raise ValueError("光谱指数所需波段不能重复")
        return self


SPECTRAL_INDEX_TOOL = {
    "type": "function",
    "function": {
        "name": "calculate_spectral_index",
        "description": "计算 NDWI、MNDWI、NDBI、EVI、SAVI、GNDVI、NDMI、NBR、MSAVI、BSI 等遥感光谱指数。",
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {"type": "string", "description": "已上传影像的 ID"},
                "index_type": {"type": "string", "enum": ["ndwi", "mndwi", "ndbi", "evi", "savi", "gndvi", "ndmi", "nbr", "msavi", "bsi"]},
                "blue_band": {"type": "integer", "default": 1},
                "green_band": {"type": "integer", "default": 2},
                "red_band": {"type": "integer", "default": 3},
                "nir_band": {"type": "integer", "default": 4},
                "swir_band": {"type": "integer", "default": 5},
                "reason": {"type": "string", "description": "计算原因说明"},
            },
            "required": ["imagery_id", "index_type"],
            "additionalProperties": False,
        },
    },
}

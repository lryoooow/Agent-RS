from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str = Field(min_length=1, max_length=16000)

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content cannot be empty.")
        return value


class ProviderConfig(BaseModel):
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    model: str | None = None
    system_prompt: str | None = None
    stream: bool = False
    provider_config: ProviderConfig | None = None
    conversation_id: str | None = None
    use_memory: bool = True
    use_rag: bool = False


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class NDVIStats(BaseModel):
    min: float
    max: float
    mean: float
    std: float


class SpectralIndexStats(BaseModel):
    index_type: str
    min: float
    max: float
    mean: float
    std: float
    nodata_pct: float = 0.0


class RasterBandStats(BaseModel):
    band: int
    min: float | None = None
    max: float | None = None
    mean: float | None = None
    std: float | None = None


class RasterCapabilities(BaseModel):
    has_blue: bool = False
    has_green: bool = False
    has_red: bool = False
    has_nir: bool = False
    has_swir: bool = False


class ToolExecutionInfo(BaseModel):
    mode: Literal["docker_mcp", "local_subprocess", "local_fallback", "failed"]
    fallback_used: bool = False
    error_code: str | None = None


class LegendInfo(BaseModel):
    label: str
    min: float
    max: float
    palette: str


class GeospatialPreviewResult(BaseModel):
    type: Literal["preview"]
    imagery_id: str
    result_url: str
    bounds: tuple[float, float, float, float] | None = None


class GeospatialNDVIResult(BaseModel):
    type: Literal["ndvi"]
    imagery_id: str
    result_url: str
    bounds: tuple[float, float, float, float] | None = None
    stats: NDVIStats
    execution: ToolExecutionInfo | None = None
    legend: LegendInfo | None = None


class GeospatialSpectralIndexResult(BaseModel):
    type: Literal["spectral_index"]
    imagery_id: str
    result_url: str
    bounds: tuple[float, float, float, float] | None = None
    index_type: str
    stats: SpectralIndexStats
    execution: ToolExecutionInfo | None = None
    legend: LegendInfo | None = None


class GeospatialCompositeResult(BaseModel):
    type: Literal["composite"]
    imagery_id: str
    result_url: str
    bounds: tuple[float, float, float, float] | None = None
    mode: str
    bands_used: list[int]
    execution: ToolExecutionInfo | None = None


class DetectionClassInfo(BaseModel):
    name: str
    label: str
    count: int
    color: str


class GeospatialDetectionResult(BaseModel):
    type: Literal["detection"]
    imagery_id: str
    result_url: str
    bounds: tuple[float, float, float, float] | None = None
    detection_count: int = 0
    score_threshold: float = 0.5
    classes: list[DetectionClassInfo] = Field(default_factory=list)
    execution: ToolExecutionInfo | None = None


class SegmentationClassInfo(BaseModel):
    name: str
    label: str
    pixel_count: int
    percentage: float
    color: str


class GeospatialSegmentationResult(BaseModel):
    type: Literal["segmentation"]
    imagery_id: str
    result_url: str
    bounds: tuple[float, float, float, float] | None = None
    total_pixels: int = 0
    classes: list[SegmentationClassInfo] = Field(default_factory=list)
    execution: ToolExecutionInfo | None = None


class RasterInspectResult(BaseModel):
    type: Literal["raster_inspect"]
    imagery_id: str
    width: int
    height: int
    band_count: int
    crs: str | None = None
    bounds: tuple[float, float, float, float] | None = None
    dtype: str | None = None
    pixel_size: tuple[float, float] | None = None
    nodata: float | int | str | None = None
    capabilities: RasterCapabilities = Field(default_factory=RasterCapabilities)
    per_band_stats: list[RasterBandStats] = Field(default_factory=list)
    execution: ToolExecutionInfo | None = None


GeospatialResult = (
    GeospatialPreviewResult
    | GeospatialNDVIResult
    | GeospatialSpectralIndexResult
    | GeospatialCompositeResult
    | GeospatialDetectionResult
    | GeospatialSegmentationResult
)
ToolResult = RasterInspectResult


class ChatResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: Usage | None = None
    finish_reason: str | None = None
    conversation_id: str | None = None
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    retrieved_chunks: int = 0
    rag_trace: dict | None = None
    agent_trace: dict | None = None
    geospatial_result: GeospatialResult | None = None
    tool_result: ToolResult | None = None

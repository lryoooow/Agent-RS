import json
import math
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator


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

    @field_validator("base_url")
    @classmethod
    def base_url_must_be_http_scheme(cls, value: str | None) -> str | None:
        # 在 API 边界快速拒掉 file://、ftp://、gopher:// 等非 http(s) scheme；
        # 主机/内网范围的深度校验在 resolve_ai_config._validate_client_base_url 完成。
        if value is None or not value.strip():
            return None
        scheme = urlsplit(value.strip()).scheme.lower()
        if scheme not in ("http", "https"):
            raise ValueError("base_url 必须是 http(s) 地址。")
        return value


class SearchConfig(BaseModel):
    """Per-request search credential; deliberately excluded from repr/log output."""

    api_key: SecretStr | None = Field(default=None, repr=False)

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        raw = value.get_secret_value().strip()
        if not raw:
            return None
        if len(raw) > 512:
            raise ValueError("Tavily API key is too long.")
        return SecretStr(raw)


class AnalysisROI(BaseModel):
    """Trusted box selection sent by the map UI for ROI-capable tools."""

    kind: Literal["geo", "pixel"]
    bbox: tuple[float, float, float, float] | None = None
    rel: tuple[float, float, float, float] | None = None

    @model_validator(mode="after")
    def validate_roi(self) -> "AnalysisROI":
        values = self.bbox if self.kind == "geo" else self.rel
        other = self.rel if self.kind == "geo" else self.bbox
        if values is None or other is not None or not all(math.isfinite(v) for v in values):
            raise ValueError("ROI fields do not match its kind.")
        x0, y0, x1, y1 = values
        if not (x0 < x1 and y0 < y1):
            raise ValueError("ROI must have a positive area.")
        if self.kind == "geo":
            if not (-180 <= x0 <= 180 and -180 <= x1 <= 180 and -90 <= y0 <= 90 and -90 <= y1 <= 90):
                raise ValueError("Geographic ROI is outside EPSG:4326 bounds.")
        elif not all(0 <= value <= 1 for value in values):
            raise ValueError("Pixel ROI coordinates must be within [0, 1].")
        return self


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=64)
    model: str | None = None
    system_prompt: str | None = None
    stream: bool = False
    provider_config: ProviderConfig | None = None
    search_config: SearchConfig | None = Field(default=None, repr=False)
    analysis_roi: AnalysisROI | None = None
    conversation_id: str | None = None
    use_memory: bool = True
    use_rag: bool = False
    metadata: dict | None = None
    thinking_strength: Literal["low", "medium", "max"] | None = None

    def tavily_api_key(self) -> str | None:
        secret = self.search_config.api_key if self.search_config else None
        return secret.get_secret_value() if secret else None

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict | None) -> dict | None:
        if value is None:
            return None
        value = dict(value)
        map_context = value.get("map_context")
        if isinstance(map_context, dict):
            map_context = dict(map_context)
            annotations = map_context.get("annotations")
            if isinstance(annotations, list):
                map_context["annotations"] = annotations[:100]
            value["map_context"] = map_context
        if len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8")) > 100_000:
            raise ValueError("Metadata exceeds the 100KB limit.")
        return value


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


class GeospatialReportResult(BaseModel):
    type: Literal["report"]
    imagery_id: str
    filename: str
    download_url: str


GeospatialResult = (
    GeospatialPreviewResult
    | GeospatialNDVIResult
    | GeospatialSpectralIndexResult
    | GeospatialCompositeResult
    | GeospatialDetectionResult
    | GeospatialSegmentationResult
    | GeospatialReportResult
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

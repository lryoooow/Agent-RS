from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InstanceSegmentArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    imagery_id: str = Field(description="平台影像 ID。")
    concepts: list[str] = Field(
        min_length=1,
        max_length=6,
        description="要寻找并逐个分割的目标概念，使用简短英文单数词，例如 building、ship、vehicle。",
    )
    red_band: int = Field(default=1, ge=1, description="红光波段号（从 1 开始）。")
    green_band: int = Field(default=2, ge=1, description="绿光波段号（从 1 开始）。")
    blue_band: int = Field(default=3, ge=1, description="蓝光波段号（从 1 开始）。")
    bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="可选地理选区 [west,south,east,north]；与 pixel_bbox 二选一。",
    )
    bbox_crs: str | None = Field(default="EPSG:4326", description="bbox 的坐标系。")
    pixel_bbox: tuple[float, float, float, float] | None = Field(
        default=None,
        description="可选归一化像素选区 [x0,y0,x1,y1]，每项范围 0–1。",
    )

    @field_validator("concepts")
    @classmethod
    def normalize_concepts(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            if any(char in value for char in ("/", "\\", "\x00", "\n", "\r")):
                raise ValueError("目标概念包含不允许的字符")
            concept = " ".join(value.strip().lower().split())
            if not concept or len(concept) > 60:
                raise ValueError("目标概念必须是 1–60 个字符的简短文本")
            if concept not in normalized:
                normalized.append(concept)
        if not normalized:
            raise ValueError("至少需要一个目标概念")
        return normalized

    @field_validator("pixel_bbox")
    @classmethod
    def validate_pixel_bbox(
        cls, value: tuple[float, float, float, float] | None,
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return value
        x0, y0, x1, y1 = value
        if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
            raise ValueError("pixel_bbox 必须满足 0≤x0<x1≤1 且 0≤y0<y1≤1")
        return value


INSTANCE_SEGMENT_TOOL_NAME = "segment_instances"
INSTANCE_SEGMENT_TOOL_DESCRIPTION = (
    "使用服务器本地 SAM3 做开放词汇实例分割，同时输出每个目标的掩膜、边界框、置信度、数量和地图矢量。"
    "适用于用户要求提取建筑物、车辆、船舶、飞机等单体目标；建筑物提取必须优先使用本工具。"
    "地物分割也使用本工具，把建筑、林地、水体、道路、农田等目标作为多个 concepts 传入。"
    "concepts 应把用户目标翻译为简短英文概念。可直接传入 bbox 或 pixel_bbox 分析当前选区。"
)

from __future__ import annotations

import re

from pydantic import BaseModel, Field, model_validator

# 接受 "EPSG:4326" / "4326" / 常见 PROJ/WKT 串。这里只做格式粗校验，
# 真正的坐标系解析在 docker 计算函数里用 rasterio.CRS 完成（权威且唯一）。
_EPSG_PATTERN = re.compile(r"^(?:EPSG:)?\d{3,6}$", re.IGNORECASE)


class ClipReprojectArguments(BaseModel):
    model_config = {"extra": "forbid"}

    imagery_id: str = Field(pattern=r"^[a-f0-9]{12}$", description="已上传影像的ID")
    dst_crs: str | None = Field(
        default=None, description="目标坐标系，如 EPSG:4326；为空则保持源坐标系（仅裁剪）"
    )
    bbox: list[float] | None = Field(
        default=None,
        description="裁剪范围 [minx, miny, maxx, maxy]；为空则不裁剪（仅重投影）",
    )
    bbox_crs: str | None = Field(
        default=None, description="bbox 所在坐标系；为空则视为与源影像相同"
    )
    resampling: str = Field(default="nearest", description="重采样方法：nearest/bilinear/cubic")
    reason: str = Field(default="用户请求裁剪/重投影", description="计算原因")

    @model_validator(mode="after")
    def _validate(self) -> "ClipReprojectArguments":
        if self.dst_crs is None and self.bbox is None:
            raise ValueError("dst_crs 与 bbox 至少需要提供一个")

        if self.dst_crs is not None and not _is_valid_crs_hint(self.dst_crs):
            raise ValueError(f"dst_crs 格式无效: {self.dst_crs}")
        if self.bbox_crs is not None and not _is_valid_crs_hint(self.bbox_crs):
            raise ValueError(f"bbox_crs 格式无效: {self.bbox_crs}")

        if self.bbox is not None:
            if len(self.bbox) != 4:
                raise ValueError("bbox 必须是 [minx, miny, maxx, maxy] 四元组")
            minx, miny, maxx, maxy = self.bbox
            if minx >= maxx or miny >= maxy:
                raise ValueError("bbox 需满足 minx<maxx 且 miny<maxy")

        if self.resampling.lower() not in {"nearest", "bilinear", "cubic"}:
            raise ValueError(f"resampling 仅支持 nearest/bilinear/cubic，收到 {self.resampling}")
        return self


def _is_valid_crs_hint(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if _EPSG_PATTERN.match(text):
        return True
    # 容许 PROJ/WKT 串（含 + 或 关键字），细节交给 rasterio 解析。
    return text.startswith("+") or "PROJCS" in text.upper() or "GEOGCS" in text.upper()


CLIP_REPROJECT_TOOL = {
    "type": "function",
    "function": {
        "name": "clip_reproject_raster",
        "description": (
            "对上传的卫星影像做裁剪和/或重投影（按 bbox 裁剪范围、转换到目标坐标系）。"
            "当用户要求裁剪影像、按范围裁切、转换投影/坐标系、重投影到 EPSG 时调用此工具。"
            "产出可下载的栅格与预览图（不会注册为新的影像 ID）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "imagery_id": {
                    "type": "string",
                    "description": "已上传影像的ID",
                },
                "dst_crs": {
                    "type": "string",
                    "description": "目标坐标系，如 EPSG:4326；为空则保持源坐标系（仅裁剪）",
                },
                "bbox": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "裁剪范围 [minx, miny, maxx, maxy]；为空则不裁剪",
                },
                "bbox_crs": {
                    "type": "string",
                    "description": "bbox 所在坐标系；为空则视为与源影像相同",
                },
                "resampling": {
                    "type": "string",
                    "description": "重采样方法：nearest/bilinear/cubic（默认 nearest）",
                },
                "reason": {
                    "type": "string",
                    "description": "计算原因说明",
                },
            },
            "required": ["imagery_id"],
            "additionalProperties": False,
        },
    },
}

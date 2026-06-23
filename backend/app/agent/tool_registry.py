from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel

from app.agent.tools.band_composite.runner import run_band_composite
from app.agent.tools.band_composite.schema import BAND_COMPOSITE_TOOL, BandCompositeArguments
from app.agent.tools.clip_reproject.runner import run_clip_reproject
from app.agent.tools.clip_reproject.schema import CLIP_REPROJECT_TOOL, ClipReprojectArguments
from app.agent.tools.cloud_mask.runner import run_cloud_mask
from app.agent.tools.cloud_mask.schema import CLOUD_MASK_TOOL, CloudMaskArguments
from app.agent.tools.detect.runner import run_detect
from app.agent.tools.detect.schema import DETECT_TOOL, DetectArguments
from app.agent.tools.ndvi.runner import run_ndvi
from app.agent.tools.ndvi.schema import NDVI_TOOL, NDVIArguments
from app.agent.tools.ocr.runner import run_ocr
from app.agent.tools.ocr.schema import OCR_TOOL, OcrArguments
from app.agent.tools.parse_document.runner import run_parse_document
from app.agent.tools.parse_document.schema import PARSE_DOCUMENT_TOOL, ParseDocumentArguments
from app.agent.tools.raster_inspect.runner import run_raster_inspect
from app.agent.tools.raster_inspect.schema import RASTER_INSPECT_TOOL, RasterInspectArguments
from app.agent.tools.report.runner import run_report
from app.agent.tools.report.schema import REPORT_TOOL, ReportArguments
from app.agent.tools.segment.runner import run_segment
from app.agent.tools.segment.schema import SEGMENT_TOOL, SegmentArguments
from app.agent.tools.spectral_index.runner import run_spectral_index
from app.agent.tools.spectral_index.schema import SPECTRAL_INDEX_TOOL, SpectralIndexArguments
from app.agent.tools.water_mask.runner import run_water_mask
from app.agent.tools.water_mask.schema import WATER_MASK_TOOL, WaterMaskArguments
from app.agent.types import ToolRunResult


ToolRunner = Callable[[BaseModel], Awaitable[ToolRunResult]]
ToolEnabled = Callable[[], bool]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    definition: dict
    argument_model: type[BaseModel]
    runner: ToolRunner
    enabled: ToolEnabled | None = None
    tags: tuple[str, ...] = ()

    def is_enabled(self) -> bool:
        return self.enabled() if self.enabled else True


async def _run_ndvi(args: NDVIArguments) -> ToolRunResult:
    return await run_ndvi(args)


async def _run_raster_inspect(args: RasterInspectArguments) -> ToolRunResult:
    return await run_raster_inspect(args)


async def _run_spectral_index(args: SpectralIndexArguments) -> ToolRunResult:
    return await run_spectral_index(args)


async def _run_band_composite(args: BandCompositeArguments) -> ToolRunResult:
    return await run_band_composite(args)


async def _run_detect(args: DetectArguments) -> ToolRunResult:
    return await run_detect(args)


async def _run_segment(args: SegmentArguments) -> ToolRunResult:
    return await run_segment(args)


async def _run_cloud_mask(args: CloudMaskArguments) -> ToolRunResult:
    return await run_cloud_mask(args)


async def _run_water_mask(args: WaterMaskArguments) -> ToolRunResult:
    return await run_water_mask(args)


async def _run_clip_reproject(args: ClipReprojectArguments) -> ToolRunResult:
    return await run_clip_reproject(args)


async def _run_parse_document(args: ParseDocumentArguments) -> ToolRunResult:
    return await run_parse_document(args)


async def _run_ocr(args: OcrArguments) -> ToolRunResult:
    return await run_ocr(args)


async def _run_report(args: ReportArguments) -> ToolRunResult:
    return await run_report(args)


TOOLS: dict[str, RegisteredTool] = {
    "calculate_ndvi": RegisteredTool(
        name="calculate_ndvi",
        definition=NDVI_TOOL,
        argument_model=NDVIArguments,
        runner=_run_ndvi,
        tags=("imagery", "ndvi", "mcp"),
    ),
    "raster_inspect": RegisteredTool(
        name="raster_inspect",
        definition=RASTER_INSPECT_TOOL,
        argument_model=RasterInspectArguments,
        runner=_run_raster_inspect,
        tags=("imagery", "inspect", "mcp"),
    ),
    "calculate_spectral_index": RegisteredTool(
        name="calculate_spectral_index",
        definition=SPECTRAL_INDEX_TOOL,
        argument_model=SpectralIndexArguments,
        runner=_run_spectral_index,
        tags=("imagery", "spectral", "mcp"),
    ),
    "render_band_composite": RegisteredTool(
        name="render_band_composite",
        definition=BAND_COMPOSITE_TOOL,
        argument_model=BandCompositeArguments,
        runner=_run_band_composite,
        tags=("imagery", "composite", "mcp"),
    ),
    "detect_objects": RegisteredTool(
        name="detect_objects",
        definition=DETECT_TOOL,
        argument_model=DetectArguments,
        runner=_run_detect,
        tags=("imagery", "detection", "mcp"),
    ),
    "segment_landcover": RegisteredTool(
        name="segment_landcover",
        definition=SEGMENT_TOOL,
        argument_model=SegmentArguments,
        runner=_run_segment,
        tags=("imagery", "segmentation", "mcp"),
    ),
    "cloud_shadow_mask": RegisteredTool(
        name="cloud_shadow_mask",
        definition=CLOUD_MASK_TOOL,
        argument_model=CloudMaskArguments,
        runner=_run_cloud_mask,
        tags=("imagery", "preprocess", "mcp"),
    ),
    "extract_water_mask": RegisteredTool(
        name="extract_water_mask",
        definition=WATER_MASK_TOOL,
        argument_model=WaterMaskArguments,
        runner=_run_water_mask,
        tags=("imagery", "preprocess", "mcp"),
    ),
    "clip_reproject_raster": RegisteredTool(
        name="clip_reproject_raster",
        definition=CLIP_REPROJECT_TOOL,
        argument_model=ClipReprojectArguments,
        runner=_run_clip_reproject,
        tags=("imagery", "preprocess", "mcp"),
    ),
    "parse_document": RegisteredTool(
        name="parse_document",
        definition=PARSE_DOCUMENT_TOOL,
        argument_model=ParseDocumentArguments,
        runner=_run_parse_document,
        tags=("document", "process"),
    ),
    "ocr_recognize": RegisteredTool(
        name="ocr_recognize",
        definition=OCR_TOOL,
        argument_model=OcrArguments,
        runner=_run_ocr,
        # 吃 imagery_id，走影像通道（不带 document tag，否则路由分流会判错通道）；
        # 领域归属由 TOOL_DOMAIN 单独映射到 document_agent，与路由 tag 正交。
        tags=("imagery", "ocr", "mcp"),
    ),
    "generate_report": RegisteredTool(
        name="generate_report",
        definition=REPORT_TOOL,
        argument_model=ReportArguments,
        runner=_run_report,
        # 不吃 imagery_id/document_id，读本对话已持久化的分析结果出 Word；
        # 自成 report 通道（ALL_REPORT_TOOLS），归属由 build_conversation_report 的对话校验保证。
        tags=("report",),
    ),
}


def list_tool_definitions(*, available_only: bool = True) -> list[dict]:
    return [
        tool.definition
        for tool in TOOLS.values()
        if not available_only or tool.is_enabled()
    ]


def get_tool(name: str) -> RegisteredTool | None:
    return TOOLS.get(name)

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

from pydantic import BaseModel

from app.agent.tools.band_composite.runner import run_band_composite
from app.agent.tools.band_composite.schema import (
    BAND_COMPOSITE_TOOL_DESCRIPTION,
    BAND_COMPOSITE_TOOL_NAME,
    BandCompositeArguments,
)
from app.agent.tools.clip_reproject.runner import run_clip_reproject
from app.agent.tools.clip_reproject.schema import (
    CLIP_REPROJECT_TOOL_DESCRIPTION,
    CLIP_REPROJECT_TOOL_NAME,
    ClipReprojectArguments,
)
from app.agent.tools.cloud_mask.runner import run_cloud_mask
from app.agent.tools.cloud_mask.schema import (
    CLOUD_MASK_TOOL_DESCRIPTION,
    CLOUD_MASK_TOOL_NAME,
    CloudMaskArguments,
)
from app.agent.tools.detect.runner import run_detect
from app.agent.tools.detect.schema import (
    DETECT_TOOL_DESCRIPTION,
    DETECT_TOOL_NAME,
    DetectArguments,
)
from app.agent.tools.ndvi.runner import run_ndvi
from app.agent.tools.ndvi.schema import NDVI_TOOL_DESCRIPTION, NDVI_TOOL_NAME, NDVIArguments
from app.agent.tools.look_at_location.runner import run_look_at_location
from app.agent.tools.look_at_location.schema import (
    LOOK_AT_LOCATION_TOOL_DESCRIPTION,
    LOOK_AT_LOCATION_TOOL_NAME,
    LookAtLocationArguments,
)
from app.agent.tools.ocr.runner import run_ocr
from app.agent.tools.ocr.schema import OCR_TOOL_DESCRIPTION, OCR_TOOL_NAME, OcrArguments
from app.agent.tools.parse_document.runner import run_parse_document
from app.agent.tools.parse_document.schema import (
    PARSE_DOCUMENT_TOOL_DESCRIPTION,
    PARSE_DOCUMENT_TOOL_NAME,
    ParseDocumentArguments,
)
from app.agent.tools.raster_inspect.runner import run_raster_inspect
from app.agent.tools.raster_inspect.schema import (
    RASTER_INSPECT_TOOL_DESCRIPTION,
    RASTER_INSPECT_TOOL_NAME,
    RasterInspectArguments,
)
from app.agent.tools.report.runner import run_report
from app.agent.tools.report.schema import (
    REPORT_TOOL_DESCRIPTION,
    REPORT_TOOL_NAME,
    ReportArguments,
)
from app.agent.tools.schema_gen import build_function_definition
from app.agent.tools.segment.runner import run_segment
from app.agent.tools.segment.schema import (
    SEGMENT_TOOL_DESCRIPTION,
    SEGMENT_TOOL_NAME,
    SegmentArguments,
)
from app.agent.tools.spectral_index.runner import run_spectral_index
from app.agent.tools.spectral_index.schema import (
    SPECTRAL_INDEX_TOOL_DESCRIPTION,
    SPECTRAL_INDEX_TOOL_NAME,
    SpectralIndexArguments,
)
from app.agent.tools.water_mask.runner import run_water_mask
from app.agent.tools.water_mask.schema import (
    WATER_MASK_TOOL_DESCRIPTION,
    WATER_MASK_TOOL_NAME,
    WaterMaskArguments,
)
from app.agent.types import ToolRunResult


ToolRunner = Callable[[BaseModel], Awaitable[ToolRunResult]]
ToolEnabled = Callable[[], bool]


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    definition: dict
    argument_model: type[BaseModel]
    runner: ToolRunner
    agent_name: str
    resource_kind: Literal["imagery", "document", "conversation", "none"]
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


async def _run_look_at_location(args: LookAtLocationArguments) -> ToolRunResult:
    return await run_look_at_location(args)


TOOLS: dict[str, RegisteredTool] = {
    "calculate_ndvi": RegisteredTool(
        name="calculate_ndvi",
        definition=build_function_definition(
            NDVI_TOOL_NAME, NDVI_TOOL_DESCRIPTION, NDVIArguments
        ),
        argument_model=NDVIArguments,
        runner=_run_ndvi,
        agent_name="spectral_agent",
        resource_kind="imagery",
        tags=("imagery", "ndvi", "mcp"),
    ),
    "raster_inspect": RegisteredTool(
        name="raster_inspect",
        definition=build_function_definition(
            RASTER_INSPECT_TOOL_NAME, RASTER_INSPECT_TOOL_DESCRIPTION, RasterInspectArguments
        ),
        argument_model=RasterInspectArguments,
        runner=_run_raster_inspect,
        agent_name="spectral_agent",
        resource_kind="imagery",
        tags=("imagery", "inspect", "mcp"),
    ),
    "calculate_spectral_index": RegisteredTool(
        name="calculate_spectral_index",
        definition=build_function_definition(
            SPECTRAL_INDEX_TOOL_NAME, SPECTRAL_INDEX_TOOL_DESCRIPTION, SpectralIndexArguments
        ),
        argument_model=SpectralIndexArguments,
        runner=_run_spectral_index,
        agent_name="spectral_agent",
        resource_kind="imagery",
        tags=("imagery", "spectral", "mcp"),
    ),
    "render_band_composite": RegisteredTool(
        name="render_band_composite",
        definition=build_function_definition(
            BAND_COMPOSITE_TOOL_NAME, BAND_COMPOSITE_TOOL_DESCRIPTION, BandCompositeArguments
        ),
        argument_model=BandCompositeArguments,
        runner=_run_band_composite,
        agent_name="spectral_agent",
        resource_kind="imagery",
        tags=("imagery", "composite", "mcp"),
    ),
    "detect_objects": RegisteredTool(
        name="detect_objects",
        definition=build_function_definition(
            DETECT_TOOL_NAME, DETECT_TOOL_DESCRIPTION, DetectArguments
        ),
        argument_model=DetectArguments,
        runner=_run_detect,
        agent_name="detection_agent",
        resource_kind="imagery",
        tags=("imagery", "detection", "mcp"),
    ),
    "segment_landcover": RegisteredTool(
        name="segment_landcover",
        definition=build_function_definition(
            SEGMENT_TOOL_NAME, SEGMENT_TOOL_DESCRIPTION, SegmentArguments
        ),
        argument_model=SegmentArguments,
        runner=_run_segment,
        agent_name="segmentation_agent",
        resource_kind="imagery",
        tags=("imagery", "segmentation", "mcp"),
    ),
    "cloud_shadow_mask": RegisteredTool(
        name="cloud_shadow_mask",
        definition=build_function_definition(
            CLOUD_MASK_TOOL_NAME, CLOUD_MASK_TOOL_DESCRIPTION, CloudMaskArguments
        ),
        argument_model=CloudMaskArguments,
        runner=_run_cloud_mask,
        agent_name="preprocess_agent",
        resource_kind="imagery",
        tags=("imagery", "preprocess", "mcp"),
    ),
    "extract_water_mask": RegisteredTool(
        name="extract_water_mask",
        definition=build_function_definition(
            WATER_MASK_TOOL_NAME, WATER_MASK_TOOL_DESCRIPTION, WaterMaskArguments
        ),
        argument_model=WaterMaskArguments,
        runner=_run_water_mask,
        agent_name="preprocess_agent",
        resource_kind="imagery",
        tags=("imagery", "preprocess", "mcp"),
    ),
    "clip_reproject_raster": RegisteredTool(
        name="clip_reproject_raster",
        definition=build_function_definition(
            CLIP_REPROJECT_TOOL_NAME, CLIP_REPROJECT_TOOL_DESCRIPTION, ClipReprojectArguments
        ),
        argument_model=ClipReprojectArguments,
        runner=_run_clip_reproject,
        agent_name="preprocess_agent",
        resource_kind="imagery",
        tags=("imagery", "preprocess", "mcp"),
    ),
    "parse_document": RegisteredTool(
        name="parse_document",
        definition=build_function_definition(
            PARSE_DOCUMENT_TOOL_NAME, PARSE_DOCUMENT_TOOL_DESCRIPTION, ParseDocumentArguments
        ),
        argument_model=ParseDocumentArguments,
        runner=_run_parse_document,
        agent_name="document_agent",
        resource_kind="document",
        tags=("document", "process"),
    ),
    "ocr_recognize": RegisteredTool(
        name="ocr_recognize",
        definition=build_function_definition(
            OCR_TOOL_NAME, OCR_TOOL_DESCRIPTION, OcrArguments
        ),
        argument_model=OcrArguments,
        runner=_run_ocr,
        agent_name="document_agent",
        resource_kind="imagery",
        # 吃 imagery_id，因此资源保护按影像处理；Agent 所有权仍是 document_agent。
        tags=("imagery", "ocr", "mcp"),
    ),
    "generate_report": RegisteredTool(
        name="generate_report",
        definition=build_function_definition(
            REPORT_TOOL_NAME, REPORT_TOOL_DESCRIPTION, ReportArguments
        ),
        argument_model=ReportArguments,
        runner=_run_report,
        agent_name="report_agent",
        resource_kind="conversation",
        # 不吃 imagery_id/document_id，读本对话已持久化的分析结果出 Word；
        # 归属由 build_conversation_report 的对话校验保证。
        tags=("report",),
    ),
    "look_at_location": RegisteredTool(
        name="look_at_location",
        definition=build_function_definition(
            LOOK_AT_LOCATION_TOOL_NAME, LOOK_AT_LOCATION_TOOL_DESCRIPTION, LookAtLocationArguments
        ),
        argument_model=LookAtLocationArguments,
        runner=_run_look_at_location,
        agent_name="navigation_agent",
        resource_kind="none",
        # 对话控图：地名→坐标让地图跳转。无 docker/影像依赖，始终可用。
        tags=("map", "location"),
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

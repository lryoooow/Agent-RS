from dataclasses import dataclass
from typing import Awaitable, Callable

from pydantic import BaseModel

from app.agent.tools.band_composite.runner import run_band_composite
from app.agent.tools.band_composite.schema import BAND_COMPOSITE_TOOL, BandCompositeArguments
from app.agent.tools.ndvi.runner import run_ndvi
from app.agent.tools.ndvi.schema import NDVI_TOOL, NDVIArguments
from app.agent.tools.raster_inspect.runner import run_raster_inspect
from app.agent.tools.raster_inspect.schema import RASTER_INSPECT_TOOL, RasterInspectArguments
from app.agent.tools.spectral_index.runner import run_spectral_index
from app.agent.tools.spectral_index.schema import SPECTRAL_INDEX_TOOL, SpectralIndexArguments
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
}


def list_tool_definitions(*, available_only: bool = True) -> list[dict]:
    return [
        tool.definition
        for tool in TOOLS.values()
        if not available_only or tool.is_enabled()
    ]


def get_tool(name: str) -> RegisteredTool | None:
    return TOOLS.get(name)

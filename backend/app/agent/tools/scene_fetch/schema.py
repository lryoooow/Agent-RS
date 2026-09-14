from pydantic import BaseModel, Field


class SceneFetchArguments(BaseModel):
    model_config = {"extra": "forbid"}

    scene_key: str = Field(
        pattern=r"^[a-f0-9]{12}$",
        description="search_imagery 结果中的场景 key（12 位十六进制）",
    )
    reason: str = Field(default="用户请求导入该场景影像", description="导入原因")


SCENE_FETCH_TOOL_NAME = "fetch_scene"
SCENE_FETCH_TOOL_DESCRIPTION = (
    "把 search_imagery 找到的某一景卫星影像合成为多波段 GeoTIFF 并导入平台影像库"
    "（Sentinel-2/Landsat 五波段：蓝/绿/红/近红外/短波红外），导入后即可用现有"
    "分析工具（NDVI、地物分类、目标检测等）直接分析。scene_key 必须来自本轮"
    "search_imagery 的结果；场景过期时请让用户重新搜索。单轮默认只能导入一景。"
)

from __future__ import annotations

from pydantic import BaseModel

from app.agent.tool_registry import RegisteredTool, get_tool, list_tool_definitions
from app.agent.types import ToolRunResult
from app.core.settings import get_settings


async def _fake_runner(_args: BaseModel) -> ToolRunResult:
    return ToolRunResult(tool_context="ok")


def reset_settings() -> None:
    get_settings.cache_clear()


def _required_fields(model: type[BaseModel]) -> set[str]:
    return {name for name, field in model.model_fields.items() if field.is_required()}


def test_unknown_tool_returns_none() -> None:
    assert get_tool("missing") is None


def test_web_search_is_not_in_tool_registry() -> None:
    definitions = list_tool_definitions(available_only=False)
    names = {item["function"]["name"] for item in definitions}

    assert "web_search" not in names
    assert "calculate_ndvi" in names
    assert "raster_inspect" in names
    assert "calculate_spectral_index" in names
    assert "render_band_composite" in names
    assert "detect_objects" in names
    assert "segment_landcover" in names
    assert "cloud_shadow_mask" in names
    assert "extract_water_mask" in names
    assert "clip_reproject_raster" in names
    assert "parse_document" in names


def test_every_registered_tool_is_allowed_by_its_route_channel() -> None:
    """每个注册工具都必须在其对应的路由候选通道里，否则 plan_validator 会把它
    静默降级为 capability_not_allowed_by_route。影像工具走 ALL_IMAGERY_TOOLS（吃 imagery_id），
    文档工具走 ALL_DOCUMENT_TOOLS（吃 document_id），按 tag 分流校验。
    新增工具时漏登记 routing 是已知坑，这条双通道回归测试守住它。"""
    from app.agent.routing import ALL_DOCUMENT_TOOLS, ALL_IMAGERY_TOOLS

    imagery_channel = set(ALL_IMAGERY_TOOLS)
    document_channel = set(ALL_DOCUMENT_TOOLS)
    # 两条通道不应有交集，否则分流语义被破坏。
    assert not (imagery_channel & document_channel), "imagery/document 通道存在重叠工具"

    unrouted: list[str] = []
    for definition in list_tool_definitions(available_only=False):
        name = definition["function"]["name"]
        tool = get_tool(name)
        assert tool is not None
        tags = set(tool.tags)
        if "document" in tags:
            if name not in document_channel:
                unrouted.append(f"{name} (document tag, missing from ALL_DOCUMENT_TOOLS)")
        else:
            if name not in imagery_channel:
                unrouted.append(f"{name} (imagery tag, missing from ALL_IMAGERY_TOOLS)")

    assert not unrouted, f"these registered tools are missing from their route channel: {unrouted}"


def test_document_tool_not_in_imagery_channel() -> None:
    """文档工具绝不能混进影像通道——否则会被当成吃 imagery_id 的工具校验。"""
    from app.agent.routing import ALL_IMAGERY_TOOLS

    assert "parse_document" not in set(ALL_IMAGERY_TOOLS)


def test_cloud_shadow_mask_capability_auto_derived() -> None:
    from app.agent.capability_registry import get_capability

    cap = get_capability("cloud_shadow_mask")
    assert cap is not None
    assert cap.kind == "tool"


def test_registered_tool_enabled_defaults_to_true() -> None:
    class Args(BaseModel):
        value: str

    tool = RegisteredTool(
        name="fake",
        definition={"type": "function"},
        argument_model=Args,
        runner=_fake_runner,
    )

    assert tool.is_enabled() is True


def test_tool_schema_required_fields_match_pydantic_models() -> None:
    for definition in list_tool_definitions(available_only=False):
        tool = get_tool(definition["function"]["name"])
        assert tool is not None
        schema = definition["function"]["parameters"]
        assert schema.get("additionalProperties") is False
        assert set(schema.get("required", [])) == _required_fields(tool.argument_model)

"""AutoGen Agent、工具注册表和访问保护之间的结构性约束。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent import tool_guards
from app.agent.engine.agents import DOMAIN_LABELS, domain_specs
from app.agent.search.schema import WebSearchArguments
from app.agent.tool_registry import TOOLS


EXPECTED_TOOLS = {
    "raster_inspect",
    "calculate_ndvi",
    "calculate_spectral_index",
    "render_band_composite",
    "cloud_shadow_mask",
    "extract_water_mask",
    "clip_reproject_raster",
    "segment_landcover",
    "detect_objects",
    "parse_document",
    "ocr_recognize",
    "generate_report",
    "look_at_location",
    "web_search",
    "search_imagery",
    "fetch_scene",
}

VALID_ARGS = {
    "raster_inspect": {"imagery_id": "94e758f38ede"},
    "calculate_ndvi": {"imagery_id": "94e758f38ede"},
    "calculate_spectral_index": {"imagery_id": "94e758f38ede", "index_type": "ndwi"},
    "render_band_composite": {"imagery_id": "94e758f38ede", "mode": "true_color"},
    "cloud_shadow_mask": {"imagery_id": "94e758f38ede"},
    "extract_water_mask": {"imagery_id": "94e758f38ede"},
    "clip_reproject_raster": {"imagery_id": "94e758f38ede", "dst_crs": "EPSG:4326"},
    "segment_landcover": {"imagery_id": "94e758f38ede"},
    "detect_objects": {"imagery_id": "94e758f38ede"},
    "parse_document": {"document_id": "11111111-1111-1111-1111-111111111111"},
    "ocr_recognize": {"imagery_id": "94e758f38ede"},
    "generate_report": {"reason": "用户请求生成报告"},
    "look_at_location": {"query": "北京"},
    "web_search": {"query": "Sentinel-2 最新数据", "reason": "需要最新信息"},
    "search_imagery": {"bbox": [113.9, 22.4, 114.3, 22.7], "reason": "找影像"},
    "fetch_scene": {"scene_key": "ab12cd34ef56", "reason": "导入分析"},
}


def test_registered_tool_inventory_is_complete() -> None:
    assert set(TOOLS) == EXPECTED_TOOLS


def test_domain_tools_each_have_exactly_one_agent_owner() -> None:
    """领域工具恰好归属一个领域 Agent；共享工具不参与归属（它们不催生 Agent）。"""
    specs = {spec.name: set(spec.tools) for spec in domain_specs()}
    domain_tools = [tool for tool in TOOLS.values() if tool.scope == "domain"]
    shared_tools = [tool for tool in TOOLS.values() if tool.scope == "shared"]

    assert set(specs) == {tool.agent_name for tool in domain_tools}
    assert set(specs).issubset(DOMAIN_LABELS)
    assert {tool.agent_name for tool in shared_tools} == {"shared"}

    owned = [tool for names in specs.values() for tool in names]
    assert len(owned) == len(set(owned)) == len(domain_tools)
    assert set(owned) == {tool.name for tool in domain_tools}


def test_shared_scope_is_exactly_the_platform_capabilities() -> None:
    """共享工具 = 联网检索 + 地图定位 + 报告生成，其余都是领域工具。"""
    shared = {tool.name for tool in TOOLS.values() if tool.scope == "shared"}
    assert shared == {"web_search", "look_at_location", "generate_report", "search_imagery", "fetch_scene"}


def test_resource_guards_are_derived_from_registry() -> None:
    imagery = {tool.name for tool in TOOLS.values() if tool.resource_kind == "imagery"}
    documents = {tool.name for tool in TOOLS.values() if tool.resource_kind == "document"}
    assert imagery
    assert documents
    assert imagery.isdisjoint(documents)
    assert "ALL_IMAGERY_TOOLS" not in tool_guards.__dict__
    assert "ALL_DOCUMENT_TOOLS" not in tool_guards.__dict__


@pytest.mark.parametrize("tool_name", sorted(EXPECTED_TOOLS))
def test_tool_argument_models_reject_unknown_fields(tool_name: str) -> None:
    model = TOOLS[tool_name].argument_model
    assert model.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        model.model_validate({**VALID_ARGS[tool_name], "unexpected_field": "must fail"})


def test_search_arguments_reject_unknown_fields() -> None:
    assert WebSearchArguments.model_config.get("extra") == "forbid"
    with pytest.raises(ValidationError):
        WebSearchArguments.model_validate(
            {"query": "latest flood data", "reason": "current", "unexpected_field": True}
        )

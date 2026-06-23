from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent import tool_guards
from app.agent.capability_registry import AGENT_CAPABILITIES, get_capability
from app.agent.domain_agents import DOMAIN_LABELS, TOOL_DOMAIN
from app.agent.routing import (
    ALL_CANDIDATE_TOOLS,
    ALL_DOCUMENT_TOOLS,
    ALL_IMAGERY_TOOLS,
    ALL_REPORT_TOOLS,
)
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
}

EXPECTED_AGENTS = {"web_search"}
EXPECTED_DOMAINS = {
    "spectral_agent",
    "preprocess_agent",
    "segmentation_agent",
    "detection_agent",
    "document_agent",
    "report_agent",
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
    "web_search": {"query": "latest flood mapping dataset", "reason": "needs current sources"},
}


def test_registered_capabilities_match_expected_inventory() -> None:
    assert set(TOOLS) == EXPECTED_TOOLS
    assert set(AGENT_CAPABILITIES) == EXPECTED_AGENTS


def test_domains_cover_every_tool_and_no_unknown_tools() -> None:
    assert set(TOOL_DOMAIN) == set(TOOLS)
    assert set(TOOL_DOMAIN.values()) == EXPECTED_DOMAINS
    assert EXPECTED_DOMAINS.issubset(set(DOMAIN_LABELS))


def test_route_channels_partition_registered_tools() -> None:
    imagery_tools = set(ALL_IMAGERY_TOOLS)
    document_tools = set(ALL_DOCUMENT_TOOLS)
    report_tools = set(ALL_REPORT_TOOLS)

    # 三个通道互不相交，且并集恰好覆盖全部注册工具（新增工具必落入某一通道）。
    assert imagery_tools | document_tools | report_tools == set(TOOLS)
    assert imagery_tools & document_tools == set()
    assert imagery_tools & report_tools == set()
    assert document_tools & report_tools == set()
    assert set(ALL_CANDIDATE_TOOLS) == set(TOOLS)


def test_tool_guards_are_derived_from_route_channels() -> None:
    # 影像/文档工具按各自归属做前置校验；报告工具不在两者内——
    # 其归属由 build_conversation_report 的对话校验保证，故 guard 不拦截（结构性约定）。
    assert tool_guards._IMAGERY_TOOLS == set(ALL_IMAGERY_TOOLS)
    assert tool_guards._DOCUMENT_TOOLS == set(ALL_DOCUMENT_TOOLS)
    assert set(ALL_REPORT_TOOLS) & (tool_guards._IMAGERY_TOOLS | tool_guards._DOCUMENT_TOOLS) == set()


@pytest.mark.parametrize("capability_name", sorted(EXPECTED_TOOLS | EXPECTED_AGENTS))
def test_capability_argument_models_reject_unknown_fields(capability_name: str) -> None:
    capability = get_capability(capability_name)
    assert capability is not None
    assert capability.argument_model.model_config.get("extra") == "forbid"

    with pytest.raises(ValidationError):
        capability.argument_model.model_validate(
            {**VALID_ARGS[capability_name], "unexpected_field": "must fail"}
        )

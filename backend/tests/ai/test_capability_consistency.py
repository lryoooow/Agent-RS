from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent import tool_guards
from app.agent.capability_registry import AGENT_CAPABILITIES, get_capability
from app.agent.domain_agents import DOMAIN_LABELS, TOOL_DOMAIN
from app.agent.routing import ALL_CANDIDATE_TOOLS, ALL_DOCUMENT_TOOLS, ALL_IMAGERY_TOOLS
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
}

EXPECTED_AGENTS = {"web_search"}
EXPECTED_DOMAINS = {
    "spectral_agent",
    "preprocess_agent",
    "segmentation_agent",
    "detection_agent",
    "document_agent",
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

    assert imagery_tools | document_tools == set(TOOLS)
    assert imagery_tools & document_tools == set()
    assert set(ALL_CANDIDATE_TOOLS) == set(TOOLS)


def test_tool_guards_are_derived_from_route_channels() -> None:
    assert tool_guards._IMAGERY_TOOLS == set(ALL_IMAGERY_TOOLS)
    assert tool_guards._DOCUMENT_TOOLS == set(ALL_DOCUMENT_TOOLS)


@pytest.mark.parametrize("capability_name", sorted(EXPECTED_TOOLS | EXPECTED_AGENTS))
def test_capability_argument_models_reject_unknown_fields(capability_name: str) -> None:
    capability = get_capability(capability_name)
    assert capability is not None
    assert capability.argument_model.model_config.get("extra") == "forbid"

    with pytest.raises(ValidationError):
        capability.argument_model.model_validate(
            {**VALID_ARGS[capability_name], "unexpected_field": "must fail"}
        )

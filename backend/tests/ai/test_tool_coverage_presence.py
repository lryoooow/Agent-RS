from __future__ import annotations

import inspect
from pathlib import Path

from app.agent.tool_registry import TOOLS


TEST_ROOT = Path(__file__).resolve().parent

# This file is a coarse guard against forgetting whole categories of tests when
# adding tools. It does not prove the business assertions are correct; concrete
# runner/compute/contract tests still carry that responsibility.
SUCCESS_MARKERS = (
    "success",
    "success_full",
    "keeps_result_shape",
    "can_run_when",
    "uses_rs_tools_client",
)
FAILURE_MARKERS = (
    "invalid",
    "not_found",
    "disabled",
    "mcp_error",
    "db_error",
    "empty",
    "truncates",
)

DETERMINISTIC_COMPUTE_COVERAGE = {
    "calculate_ndvi": "test_ndvi_compute.py",
    "raster_inspect": "test_rs_tools_compute.py",
    "calculate_spectral_index": "test_rs_tools_compute.py",
    "render_band_composite": "test_rs_tools_compute.py",
    "cloud_shadow_mask": "test_cloud_mask_compute.py",
    "extract_water_mask": "test_water_mask_compute.py",
    "clip_reproject_raster": "test_clip_reproject_compute.py",
    "ocr_recognize": "test_ocr_compute.py",
}


def _tool_slug(tool_name: str) -> str:
    schema_path = Path(inspect.getfile(TOOLS[tool_name].argument_model))
    return schema_path.parent.name


def _runner_test_path(tool_name: str) -> Path:
    return TEST_ROOT / f"test_{_tool_slug(tool_name)}_runner.py"


def test_every_registered_tool_has_runner_test_file() -> None:
    missing = [
        (tool_name, _runner_test_path(tool_name).name)
        for tool_name in sorted(TOOLS)
        if not _runner_test_path(tool_name).exists()
    ]

    assert not missing


def test_runner_test_files_cover_success_and_failure_paths() -> None:
    weak: list[tuple[str, str]] = []

    for tool_name in sorted(TOOLS):
        text = _runner_test_path(tool_name).read_text(encoding="utf-8")
        if not any(marker in text for marker in SUCCESS_MARKERS):
            weak.append((tool_name, "missing success marker"))
        if not any(marker in text for marker in FAILURE_MARKERS):
            weak.append((tool_name, "missing failure marker"))

    assert not weak


def test_mcp_runner_tests_cover_transport_error_paths() -> None:
    missing = []

    for tool_name, tool in sorted(TOOLS.items()):
        if "mcp" not in tool.tags:
            continue
        text = _runner_test_path(tool_name).read_text(encoding="utf-8")
        if "mcp_error" not in text:
            missing.append(tool_name)

    assert not missing


def test_deterministic_compute_tools_have_compute_coverage() -> None:
    missing = [
        (tool_name, filename)
        for tool_name, filename in sorted(DETERMINISTIC_COMPUTE_COVERAGE.items())
        if not (TEST_ROOT / filename).exists()
    ]

    assert not missing


def test_cross_cutting_contract_tests_remain_present() -> None:
    consistency = (TEST_ROOT / "test_capability_consistency.py").read_text(encoding="utf-8")
    mcp_exposure = (TEST_ROOT / "test_mcp_exposure.py").read_text(encoding="utf-8")
    tool_guards = (TEST_ROOT / "test_tool_guards.py").read_text(encoding="utf-8")

    assert "test_route_channels_partition_registered_tools" in consistency
    assert "test_tool_guards_are_derived_from_route_channels" in consistency
    assert "test_actual_backend_mcp_payload_fields_are_accepted_by_container_schemas" in mcp_exposure
    assert "test_ocr_recognize_uses_imagery_owner_guard" in tool_guards

from __future__ import annotations

from pathlib import Path

from app.agent.tool_registry import TOOLS


MCP_TOOL_NAMES = {
    "calculate_ndvi",
    "raster_inspect",
    "calculate_spectral_index",
    "render_band_composite",
    "cloud_shadow_mask",
    "extract_water_mask",
    "clip_reproject_raster",
}


def test_backend_registers_all_rs_tools() -> None:
    assert MCP_TOOL_NAMES.issubset(set(TOOLS))


def test_rs_tools_container_exposes_backend_tool_names() -> None:
    import sys

    rs_tools_dir = Path(__file__).resolve().parents[3] / "docker" / "rs_tools"
    sys.path.insert(0, str(rs_tools_dir))
    try:
        import mcp_server

        server_tools = {tool["name"] for tool in mcp_server.TOOL_DEFINITIONS}
    finally:
        sys.path.remove(str(rs_tools_dir))

    assert MCP_TOOL_NAMES == server_tools


def test_legacy_ndvi_mcp_path_is_not_reintroduced() -> None:
    root = Path(__file__).resolve().parents[3]
    forbidden = ("ndvi_client", "docker/ndvi", "docker\\ndvi", "ndvi_mcp", "ndvi-mcp")
    allowed_files = {
        Path("backend/tests/ai/test_tool_uniformity.py"),
    }
    offenders: list[tuple[str, str]] = []

    for path in _text_files(root):
        rel = path.relative_to(root)
        if rel in allowed_files:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for marker in forbidden:
            if marker in text:
                offenders.append((rel.as_posix(), marker))

    assert not offenders


def _text_files(root: Path) -> list[Path]:
    included_roots = [
        root / "backend" / "app",
        root / "backend" / "tests",
        root / "docker" / "rs_tools",
    ]
    result: list[Path] = []
    for base in included_roots:
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts:
                continue
            if path.suffix not in {".py", ".toml", ".md", ".txt"}:
                continue
            result.append(path)
    return result

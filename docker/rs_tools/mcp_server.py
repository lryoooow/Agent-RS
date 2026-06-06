from __future__ import annotations

import json
import sys
import traceback

from compute_band_composite import render as render_band_composite
from compute_ndvi import compute as compute_ndvi
from compute_raster_inspect import inspect as inspect_raster
from compute_spectral_index import compute as compute_spectral_index


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "rs-tools-mcp"
SERVER_VERSION = "0.1.0"

TOOL_DEFINITIONS = [
    {
        "name": "raster_inspect",
        "description": "Inspect GeoTIFF metadata, per-band statistics, and basic spectral capabilities.",
        "inputSchema": {
            "type": "object",
            "properties": {"input_path": {"type": "string"}},
            "required": ["input_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calculate_ndvi",
        "description": "Compute NDVI from a multispectral GeoTIFF.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "red_band": {"type": "integer", "default": 3},
                "nir_band": {"type": "integer", "default": 4},
            },
            "required": ["input_path", "output_dir"],
            "additionalProperties": False,
        },
    },
    {
        "name": "calculate_spectral_index",
        "description": "Compute NDWI, MNDWI, NDBI, EVI, or SAVI from a multispectral GeoTIFF.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "index_type": {"type": "string"},
                "blue_band": {"type": "integer", "default": 1},
                "green_band": {"type": "integer", "default": 2},
                "red_band": {"type": "integer", "default": 3},
                "nir_band": {"type": "integer", "default": 4},
                "swir_band": {"type": "integer", "default": 5},
            },
            "required": ["input_path", "output_dir", "index_type"],
            "additionalProperties": False,
        },
    },
    {
        "name": "render_band_composite",
        "description": "Render true-color, false-color, or custom RGB band composites as PNG.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "mode": {"type": "string"},
                "bands": {"type": "array", "items": {"type": "integer"}},
                "max_dimension": {"type": "integer", "default": 2048},
            },
            "required": ["input_path", "output_dir", "mode"],
            "additionalProperties": False,
        },
    },
]


def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(request: dict) -> dict | None:
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _ok(
            req_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "tools/list":
        return _ok(req_id, {"tools": TOOL_DEFINITIONS})
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "raster_inspect":
                result = inspect_raster(input_path=args["input_path"])
            elif name == "calculate_ndvi":
                result = compute_ndvi(**args)
            elif name == "calculate_spectral_index":
                result = compute_spectral_index(**args)
            elif name == "render_band_composite":
                result = render_band_composite(**args)
            else:
                return _err(req_id, -32601, f"Unknown tool: {name}")
            return _ok(
                req_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result)}],
                    "isError": False,
                    "structuredContent": result,
                },
            )
        except Exception as exc:
            return _ok(
                req_id,
                {
                    "content": [{"type": "text", "text": f"{name} execution failed: {exc}"}],
                    "isError": True,
                },
            )
    return _err(req_id, -32601, f"Method not found: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.stderr.write(f"Invalid JSON: {exc}\n")
            sys.stderr.flush()
            continue
        try:
            response = handle(request)
        except Exception:
            traceback.print_exc(file=sys.stderr)
            response = _err(request.get("id"), -32603, "Internal server error")
        if response is None:
            continue
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

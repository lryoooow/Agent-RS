"""Minimal MCP server (JSON-RPC 2.0 over stdio) exposing the calculate_ndvi tool.

Implements: initialize, tools/list, tools/call.
Reads JSON-RPC requests from stdin (one per line), writes responses to stdout.
"""

import json
import sys
import traceback

from compute_ndvi import compute


PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "ndvi-mcp"
SERVER_VERSION = "0.1.0"

TOOL_DEFINITION = {
    "name": "calculate_ndvi",
    "description": "Compute NDVI from a multispectral GeoTIFF. Reads input file, writes ndvi.tif/ndvi_colored.png/stats.json to output_dir, returns stats.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "input_path": {"type": "string", "description": "Absolute path to the source GeoTIFF inside the container."},
            "output_dir": {"type": "string", "description": "Absolute output directory inside the container."},
            "red_band": {"type": "integer", "default": 3, "description": "Red band index (1-based)."},
            "nir_band": {"type": "integer", "default": 4, "description": "NIR band index (1-based)."},
        },
        "required": ["input_path", "output_dir"],
        "additionalProperties": False,
    },
}


def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def handle(request: dict) -> dict | None:
    method = request.get("method")
    req_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return _ok(req_id, {"tools": [TOOL_DEFINITION]})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        if name != "calculate_ndvi":
            return _err(req_id, -32601, f"Unknown tool: {name}")
        try:
            stats = compute(
                input_path=args["input_path"],
                output_dir=args["output_dir"],
                red_band=int(args.get("red_band", 3)),
                nir_band=int(args.get("nir_band", 4)),
            )
            return _ok(req_id, {
                "content": [{"type": "text", "text": json.dumps(stats)}],
                "isError": False,
                "structuredContent": stats,
            })
        except Exception as exc:
            return _ok(req_id, {
                "content": [{"type": "text", "text": f"NDVI execution failed: {exc}"}],
                "isError": True,
            })

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

from __future__ import annotations

import json
import sys
import traceback

from compute_ocr import compute as compute_ocr


PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "rs-doc-mcp"
SERVER_VERSION = "0.1.0"


TOOL_DEFINITIONS = [
    {
        "name": "ocr_recognize",
        "description": "对栅格影像做光学字符识别（RapidOCR / PP-OCRv4，中英文）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "input_path": {"type": "string"},
                "output_dir": {"type": "string"},
                "red_band": {"type": "integer"},
                "green_band": {"type": "integer"},
                "blue_band": {"type": "integer"},
                "grayscale": {"type": "boolean"},
                "max_dimension": {"type": "integer"},
                "min_confidence": {"type": "number"},
            },
            "required": ["input_path", "output_dir"],
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
                "protocolVersion": "2024-11-05" if params.get("protocolVersion") == "2024-11-05" else PROTOCOL_VERSION,
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
            if name == "ocr_recognize":
                result = compute_ocr(**args)
                if (params.get("_meta") or {}).get("agent-rs/compact-result"):
                    text = result["full_text"]
                    result = {k: v for k, v in result.items() if k not in ("full_text", "blocks")}
                    result.update(full_text=text[:4096], truncated=len(text) > 4096)
            else:
                return _err(req_id, -32601, f"Unknown tool: {name}")
            return _ok(
                req_id,
                {
                    "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
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
        token = (request.get("params", {}).get("_meta") or {}).get("progressToken")
        out = sys.stdout
        def progress(value, total, message):
            if token is not None and request.get("method") == "tools/call":
                notice = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {
                    "progressToken": token, "progress": value, "total": total, "message": message}}
                print(json.dumps(notice), file=out, flush=True)
        try:
            progress(0, 100, "已开始处理影像")
            response = handle(request)
            if response and "result" in response and not response["result"].get("isError"):
                progress(100, 100, "算子已完成")
        except Exception:
            traceback.print_exc(file=sys.stderr)
            response = _err(request.get("id"), -32603, "Internal server error")
        if response is None:
            continue
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

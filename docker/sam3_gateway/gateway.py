"""MCP gateway for an operator-provided, separately licensed SAM3 inference service."""
import hashlib
import hmac
import json
import os
from pathlib import PurePosixPath, PureWindowsPath
import re
from typing import Annotated
from urllib.parse import urlsplit

from fastmcp import Context, FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
import httpx2
from pydantic import Field

JOB = re.compile(r"(?:[a-f0-9]{12}|\.staging/imagery_[a-f0-9]{12}_[A-Za-z0-9_-]{1,64})/results/\.sam3_[a-f0-9]{32}\Z")
FILES = ("overlay_png", "union_png", "labels_npy", "instances_json", "metrics_json")
SUMMARY = ("device", "counts", "instance_count", "union_pixels", "input_size", "tile_count")


class GatewayToken(TokenVerifier):
    def __init__(self, secret):
        super().__init__(required_scopes=["infer"])
        self.digest = hashlib.sha256(secret.encode()).digest()

    async def verify_token(self, token):
        if hmac.compare_digest(self.digest, hashlib.sha256(token.encode()).digest()):
            return AccessToken(token=token, client_id="agent-rs", scopes=["infer"])
        return None


def build_gateway(endpoint, shared_root, timeout, *, auth=None, transport=None):
    parsed = urlsplit(endpoint)
    root = PurePosixPath(shared_root)
    if not root.is_absolute():
        root = PureWindowsPath(shared_root)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not root.is_absolute()):
        raise ValueError("Configure the private inference URL and its absolute imagery root")
    server = FastMCP("Agent-RS SAM3 gateway", auth=auth)

    @server.tool(name="segment_instances", annotations={
        "readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False})
    async def segment(job: Annotated[str, Field(max_length=180)],
                      concepts: Annotated[list[str], Field(min_length=1, max_length=6)], ctx: Context) -> dict:
        """Forward a platform-generated image job to the configured private segmentation service."""
        if not JOB.fullmatch(job) or any(not c.strip() or len(c) > 60 or any(ch in c for ch in "/\\\x00\r\n") for c in concepts):
            raise ValueError("Invalid segmentation job or concepts")
        directory = root / job
        payload = {"input_path": str(directory / "input.png"), "output_dir": str(directory), "concepts": concepts}
        await ctx.report_progress(0, None, "正在向私有 SAM3 服务提交影像")
        try:
            async with httpx2.AsyncClient(transport=transport, timeout=timeout, trust_env=False,
                                          follow_redirects=False) as client:
                async with client.stream("POST", endpoint.rstrip("/") + "/infer", json=payload) as response:
                    settled = response.is_success or response.headers.get("X-SAM3-Settled") == "1"
                    if not response.is_success:
                        return {"settled": settled, "error": "service_error"}
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > 16 * 1024 * 1024:
                            return {"settled": True, "error": "invalid_result"}
                        data.extend(chunk)
        except httpx2.TimeoutException:
            return {"settled": False, "error": "inference_timeout"}
        except httpx2.ConnectError:
            return {"settled": True, "error": "service_unavailable"}
        except httpx2.HTTPError:
            return {"settled": False, "error": "service_error"}
        try:
            result = json.loads(data)
            if not isinstance(result, dict) or any(not isinstance(result.get(k), str) or
                    not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,180}", result[k]) for k in FILES):
                raise ValueError("invalid artifact name")
        except (UnicodeError, ValueError):
            return {"settled": True, "error": "invalid_result"}
        await ctx.report_progress(1, 1, "私有 SAM3 服务已返回结果")
        return {"settled": True, "output": {k: result[k] for k in (*FILES, *SUMMARY) if k in result}}
    return server


if __name__ == "__main__":
    mode = os.environ.get("MCP_TRANSPORT", "stdio")
    verifier = None
    if mode == "streamable_http":
        secret = os.environ.get("MCP_OPERATOR_TOKEN")
        if not secret:
            raise SystemExit("MCP_OPERATOR_TOKEN is required for HTTP")
        verifier = GatewayToken(secret)
    gateway = build_gateway(os.environ["SAM3_UPSTREAM_URL"], os.environ["SAM3_UPSTREAM_ROOT"],
                            float(os.environ.get("SAM3_INFERENCE_TIMEOUT_SECONDS", "900")), auth=verifier)
    if mode == "stdio":
        gateway.run(transport="stdio", show_banner=False)
    elif mode == "streamable_http":
        gateway.run(transport="streamable-http", host=os.environ.get("SAM3_GATEWAY_BIND", "127.0.0.1"),
                    port=int(os.environ.get("SAM3_GATEWAY_PORT", "18133")), path="/mcp", show_banner=False)
    else:
        raise SystemExit("Unknown MCP_TRANSPORT")

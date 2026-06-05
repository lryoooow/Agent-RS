from __future__ import annotations

import asyncio
import json
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


class MCPCallError(Exception):
    """Raised when the MCP server returns an error or the transport fails."""


class StdioMCPClient:
    def __init__(
        self,
        *,
        command: list[str],
        timeout_seconds: int,
        client_name: str,
        client_version: str,
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        self.client_name = client_name
        self.client_version = client_version

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        completed = False
        try:
            result = await asyncio.wait_for(
                self._handshake_and_call(proc, tool_name, arguments),
                timeout=self.timeout_seconds,
            )
            completed = True
            return result
        except Exception:
            await self._kill_process(proc)
            raise
        finally:
            if completed:
                await self._close_stdin_and_wait(proc)

    async def _handshake_and_call(
        self,
        proc: asyncio.subprocess.Process,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        await self._send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {
                        "name": self.client_name,
                        "version": self.client_version,
                    },
                },
            },
        )
        init_resp = await self._recv(proc)
        if "error" in init_resp:
            raise MCPCallError(f"initialize failed: {init_resp['error']}")

        await self._send(
            proc,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        await self._send(
            proc,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments,
                },
            },
        )
        call_resp = await self._recv(proc)
        if "error" in call_resp:
            raise MCPCallError(f"tools/call failed: {call_resp['error']}")

        result = call_resp.get("result") or {}
        if result.get("isError"):
            text = ""
            for item in result.get("content", []):
                if item.get("type") == "text":
                    text = item.get("text", "")
                    break
            raise MCPCallError(text or "tool returned isError without message")

        structured_content = result.get("structuredContent")
        if not isinstance(structured_content, dict):
            raise MCPCallError("missing structuredContent in tool response")
        return structured_content

    @staticmethod
    async def _send(proc: asyncio.subprocess.Process, msg: dict[str, Any]) -> None:
        if proc.stdin is None:
            raise MCPCallError("MCP process stdin is not available")
        line = (json.dumps(msg) + "\n").encode("utf-8")
        proc.stdin.write(line)
        await proc.stdin.drain()

    @staticmethod
    async def _recv(proc: asyncio.subprocess.Process) -> dict[str, Any]:
        if proc.stdout is None:
            raise MCPCallError("MCP process stdout is not available")
        line = await proc.stdout.readline()
        if not line:
            stderr = ""
            if proc.stderr is not None:
                stderr = (await proc.stderr.read()).decode(errors="replace")
            raise MCPCallError(f"MCP server closed stdout. stderr: {stderr[:500]}")
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise MCPCallError(f"invalid JSON from server: {exc}: {line!r}")

    @staticmethod
    async def _close_stdin_and_wait(proc: asyncio.subprocess.Process) -> None:
        try:
            if proc.stdin is not None and not proc.stdin.is_closing():
                proc.stdin.close()
                wait_closed = getattr(proc.stdin, "wait_closed", None)
                if wait_closed is not None:
                    await wait_closed()
        except Exception:
            pass

        if getattr(proc, "returncode", None) is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()

    @staticmethod
    async def _kill_process(proc: asyncio.subprocess.Process) -> None:
        if getattr(proc, "returncode", None) is None:
            proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass

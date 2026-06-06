from __future__ import annotations

import asyncio
import json
from io import StringIO

import pytest

import app.mcp.client as mcp_client
from app.mcp.client import MCPCallError, StdioMCPClient


class FakeStdin:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeStdout:
    def __init__(self, rows: list[dict] | list[bytes]) -> None:
        self.rows = [
            row if isinstance(row, bytes) else (json.dumps(row) + "\n").encode("utf-8")
            for row in rows
        ]

    async def readline(self) -> bytes:
        if not self.rows:
            return b""
        return self.rows.pop(0)


class FakeStderr:
    def __init__(self, content: bytes = b"") -> None:
        self.content = content

    async def read(self) -> bytes:
        return self.content


class FakeProcess:
    def __init__(self, stdout_rows, stderr: bytes = b"") -> None:
        self.stdin = FakeStdin()
        self.stdout = FakeStdout(stdout_rows)
        self.stderr = FakeStderr(stderr)
        self.killed = False

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> int:
        return 0


def _fake_create(proc: FakeProcess):
    async def create(*_args, **_kwargs):
        return proc

    return create


def _client() -> StdioMCPClient:
    return StdioMCPClient(
        command=["fake"],
        timeout_seconds=1,
        client_name="test-client",
        client_version="0.1",
    )


class FakeSyncProcess:
    def __init__(self, stdout_rows) -> None:
        self.stdin = FakeSyncStdin()
        self.stdout = StringIO(
            "".join(json.dumps(row) + "\n" for row in stdout_rows)
        )
        self.stderr = StringIO("")
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeSyncStdin(StringIO):
    @property
    def closed(self) -> bool:
        return False

    def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_stdio_mcp_client_calls_tool_success(monkeypatch) -> None:
    proc = FakeProcess([
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": {"mean": 0.5}}},
    ])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create(proc))

    result = await _client().call_tool("calculate_ndvi", {"input_path": "/data/a.tif"})

    assert result == {"mean": 0.5}
    assert len(proc.stdin.writes) == 3
    assert b"initialize" in proc.stdin.writes[0]
    assert b"tools/call" in proc.stdin.writes[2]


@pytest.mark.asyncio
async def test_stdio_mcp_client_raises_on_tool_error(monkeypatch) -> None:
    proc = FakeProcess([
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "id": 2, "error": {"message": "bad"}},
    ])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create(proc))

    with pytest.raises(MCPCallError, match="tools/call failed"):
        await _client().call_tool("calculate_ndvi", {})


@pytest.mark.asyncio
async def test_stdio_mcp_client_raises_on_is_error(monkeypatch) -> None:
    proc = FakeProcess([
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"isError": True, "content": [{"type": "text", "text": "tool failed"}]},
        },
    ])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create(proc))

    with pytest.raises(MCPCallError, match="tool failed"):
        await _client().call_tool("calculate_ndvi", {})


@pytest.mark.asyncio
async def test_stdio_mcp_client_reports_closed_stdout_stderr(monkeypatch) -> None:
    proc = FakeProcess([], stderr=b"container failed")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create(proc))

    with pytest.raises(MCPCallError, match="container failed"):
        await _client().call_tool("calculate_ndvi", {})


@pytest.mark.asyncio
async def test_stdio_mcp_client_raises_on_invalid_json(monkeypatch) -> None:
    proc = FakeProcess([b"not-json\n"])
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_create(proc))

    with pytest.raises(MCPCallError, match="invalid JSON"):
        await _client().call_tool("calculate_ndvi", {})


@pytest.mark.asyncio
async def test_stdio_mcp_client_falls_back_when_async_subprocess_is_unavailable(
    monkeypatch,
) -> None:
    async def unsupported_async_subprocess(*_args, **_kwargs):
        raise NotImplementedError

    proc = FakeSyncProcess([
        {"jsonrpc": "2.0", "id": 1, "result": {}},
        {"jsonrpc": "2.0", "id": 2, "result": {"structuredContent": {"mean": 0.5}}},
    ])

    monkeypatch.setattr(asyncio, "create_subprocess_exec", unsupported_async_subprocess)
    monkeypatch.setattr(mcp_client.subprocess, "Popen", lambda *_args, **_kwargs: proc)

    result = await _client().call_tool("calculate_ndvi", {"input_path": "/data/a.tif"})

    assert result == {"mean": 0.5}
    written = proc.stdin.getvalue()
    assert "initialize" in written
    assert "tools/call" in written

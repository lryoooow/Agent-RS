from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import threading
from typing import Any

PROTOCOL_VERSION = "2024-11-05"

logger = logging.getLogger(__name__)

# G10：docker kill 的等待上限；容器已退出/不存在时 docker kill 非零返回，忽略。
CONTAINER_KILL_TIMEOUT_SECONDS = 10.0


class MCPCallError(Exception):
    """Raised when the MCP server returns an error or the transport fails."""


def _container_name_from_command(command: list[str]) -> str | None:
    """从命令行解析 ``--name <value>``（G10：超时按名 kill 容器用）。"""
    for index, arg in enumerate(command):
        if arg.startswith("--name="):
            value = arg.split("=", 1)[1]
            return value or None
        if arg == "--name" and index + 1 < len(command):
            return command[index + 1] or None
    return None


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
        # G10：docker run 的本地客户端进程被 kill 并不会停止容器本体；
        # 命令带 --name 时超时/取消改为（并）按名 docker kill 容器。
        self._container_name = _container_name_from_command(command)

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except NotImplementedError:
            return await self._call_tool_sync_with_timeout(tool_name, arguments)
        completed = False
        try:
            result = await asyncio.wait_for(
                self._handshake_and_call(proc, tool_name, arguments),
                timeout=self.timeout_seconds,
            )
            completed = True
            return result
        except (asyncio.CancelledError, Exception):
            # G10：先按名杀容器，再回收本地 docker 客户端进程。
            await self._kill_container()
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

    async def _kill_container(self) -> None:
        """G10：按名 docker kill 容器。

        kill 本地 ``docker run`` 客户端进程不会停止容器本体——容器继续占用
        CPU/内存/挂载直至自行结束。命令带 ``--name`` 时按名杀容器；容器已
        退出（``--rm`` 自动清理）时 docker kill 非零返回，属预期，忽略。
        """
        if not self._container_name:
            return
        try:
            kill = await asyncio.create_subprocess_exec(
                "docker",
                "kill",
                self._container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(kill.wait(), timeout=CONTAINER_KILL_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 清理失败不得掩盖原始异常
            logger.debug("docker kill %s failed during cleanup", self._container_name, exc_info=True)

    def _kill_container_sync(self) -> None:
        if not self._container_name:
            return
        try:
            subprocess.run(
                ["docker", "kill", self._container_name],
                capture_output=True,
                timeout=CONTAINER_KILL_TIMEOUT_SECONDS,
                check=False,
            )
        except Exception:  # noqa: BLE001 - 清理失败不得掩盖原始异常
            logger.debug("docker kill %s failed during cleanup", self._container_name, exc_info=True)

    async def _call_tool_sync_with_timeout(
        self,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        proc_holder: dict[str, subprocess.Popen] = {}
        cancelled = threading.Event()
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._call_tool_sync, tool_name, arguments, proc_holder, cancelled),
                timeout=self.timeout_seconds,
            )
        except (asyncio.TimeoutError, asyncio.CancelledError):
            cancelled.set()
            proc = proc_holder.get("proc")
            if proc is not None:
                # G10：线程内先按名杀容器再回收本地进程（同异步路径的顺序）。
                await asyncio.to_thread(self._kill_container_sync)
                await asyncio.to_thread(self._kill_process_sync, proc)
            raise

    def _call_tool_sync(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        proc_holder: dict[str, subprocess.Popen] | None = None,
        cancelled: threading.Event | None = None,
    ) -> dict[str, Any]:
        proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        if proc_holder is not None:
            proc_holder["proc"] = proc
        completed = False
        try:
            # Popen can finish after the caller has already cancelled. Do not
            # start the handshake/tool in that race; the exception closes it.
            if cancelled is not None and cancelled.is_set():
                raise MCPCallError("MCP execution cancelled before startup completed")
            result = self._handshake_and_call_sync(proc, tool_name, arguments)
            completed = True
            return result
        except Exception:
            # G10：先按名杀容器，再回收本地进程（同异步路径的顺序）。
            self._kill_container_sync()
            self._kill_process_sync(proc)
            raise
        finally:
            if completed:
                self._close_stdin_and_wait_sync(proc)

    def _handshake_and_call_sync(
        self,
        proc: subprocess.Popen,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        self._send_sync(
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
        init_resp = self._recv_sync(proc)
        if "error" in init_resp:
            raise MCPCallError(f"initialize failed: {init_resp['error']}")

        self._send_sync(
            proc,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        self._send_sync(
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
        call_resp = self._recv_sync(proc)
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
    def _send_sync(proc: subprocess.Popen, msg: dict[str, Any]) -> None:
        if proc.stdin is None:
            raise MCPCallError("MCP process stdin is not available")
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    @staticmethod
    def _recv_sync(proc: subprocess.Popen) -> dict[str, Any]:
        if proc.stdout is None:
            raise MCPCallError("MCP process stdout is not available")
        line = proc.stdout.readline()
        if not line:
            stderr = ""
            if proc.stderr is not None:
                stderr = proc.stderr.read()
            raise MCPCallError(f"MCP server closed stdout. stderr: {stderr[:500]}")
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise MCPCallError(f"invalid JSON from server: {exc}: {line!r}")

    @staticmethod
    def _close_stdin_and_wait_sync(proc: subprocess.Popen) -> None:
        try:
            if proc.stdin is not None and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass

        if proc.poll() is None:
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    @staticmethod
    def _kill_process_sync(proc: subprocess.Popen) -> None:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            pass

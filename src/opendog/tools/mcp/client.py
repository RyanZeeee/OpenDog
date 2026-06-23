from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Optional, Union
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)


class MCPClientError(Exception):
    pass


def _format_mcp_tool_result(result: dict) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
            else:
                parts.append(json.dumps(item, ensure_ascii=False))
        if parts:
            return "\n".join(parts)
    return json.dumps(result, ensure_ascii=False)


MCPClient = Union["StdioMCPClient", "SSEMCPClient"]


class StdioMCPClient:
    def __init__(self, server_config: Any) -> None:
        self.server_config = server_config
        self.name = server_config.name
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._process: Optional[asyncio.subprocess.Process] = None
        self._request_id = 0
        self._request_lock: Optional[asyncio.Lock] = None
        self._tools: list[dict] = []

    def start(self, timeout: float = 20.0) -> list[dict]:
        if self._loop is not None:
            return self._tools

        ready = threading.Event()

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._request_lock = asyncio.Lock()
            ready.set()
            loop.run_forever()

        self._thread = threading.Thread(
            target=run_loop,
            name=f"mcp-{self.name}",
            daemon=True,
        )
        self._thread.start()
        ready.wait(timeout=timeout)

        if self._loop is None:
            raise MCPClientError(f"Failed to start MCP event loop: {self.name}")

        future = asyncio.run_coroutine_threadsafe(self._async_start(), self._loop)
        try:
            self._tools = future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise MCPClientError(f"Timed out starting MCP server: {self.name}") from exc
        return self._tools

    def call_tool(self, tool_name: str, arguments: dict, timeout: float = 60.0) -> str:
        if self._loop is None:
            self.start()

        if self._loop is None:
            raise MCPClientError(f"MCP client is not running: {self.name}")

        future = asyncio.run_coroutine_threadsafe(
            self._async_call_tool(tool_name, arguments),
            self._loop,
        )
        try:
            result = future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise MCPClientError(f"Timed out calling MCP tool {tool_name}") from exc
        return self._format_tool_result(result)

    def stop(self, timeout: float = 5.0) -> None:
        if self._loop is None:
            return

        future = asyncio.run_coroutine_threadsafe(self._async_stop(), self._loop)
        try:
            future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=timeout)

        self._loop = None
        self._thread = None
        self._process = None
        self._request_lock = None
        self._tools = []

    async def _async_start(self) -> list[dict]:
        env = os.environ.copy()
        env.update(self.server_config.env)

        self._process = await asyncio.create_subprocess_exec(
            self.server_config.command,
            *self.server_config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        asyncio.create_task(self._drain_stderr())

        await self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "opendog",
                    "version": "0.1.0",
                },
            },
        )
        await self._notify("notifications/initialized", {})
        tools_result = await self._request("tools/list", {})
        return tools_result.get("tools", [])

    async def _async_stop(self) -> None:
        process = self._process
        if process is None or process.returncode is not None:
            return

        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=3)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def _async_call_tool(self, tool_name: str, arguments: dict) -> dict:
        return await self._request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments,
            },
        )

    async def _request(self, method: str, params: dict) -> dict:
        if self._request_lock is None:
            raise MCPClientError(f"MCP client lock is not ready: {self.name}")

        async with self._request_lock:
            request_id = self._next_request_id()
            await self._send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )

            while True:
                message = await self._read_message()
                if message.get("id") != request_id:
                    continue

                if "error" in message:
                    raise MCPClientError(
                        f"MCP request failed on {self.name}: {message['error']}"
                    )
                return message.get("result", {})

    async def _notify(self, method: str, params: dict) -> None:
        await self._send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            }
        )

    async def _send(self, payload: dict) -> None:
        process = self._require_process()
        if process.stdin is None:
            raise MCPClientError(f"MCP stdin is not available: {self.name}")

        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
        process.stdin.write(data)
        await process.stdin.drain()

    async def _read_message(self) -> dict:
        process = self._require_process()
        if process.stdout is None:
            raise MCPClientError(f"MCP stdout is not available: {self.name}")

        while True:
            line = await process.stdout.readline()
            if not line:
                raise MCPClientError(f"MCP server stopped: {self.name}")

            stripped = line.strip()
            if not stripped:
                continue

            if stripped.lower().startswith(b"content-length:"):
                return await self._read_content_length_message(stripped)

            try:
                return json.loads(stripped.decode("utf-8"))
            except json.JSONDecodeError:
                logger.debug("Ignoring non-JSON MCP stdout from %s: %r", self.name, line)

    async def _read_content_length_message(self, first_header: bytes) -> dict:
        process = self._require_process()
        if process.stdout is None:
            raise MCPClientError(f"MCP stdout is not available: {self.name}")

        headers = [first_header]
        while True:
            line = await process.stdout.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            headers.append(line.strip())

        content_length = None
        for header in headers:
            key, _, value = header.partition(b":")
            if key.lower() == b"content-length":
                content_length = int(value.strip())
                break

        if content_length is None:
            raise MCPClientError(f"MCP message missing Content-Length: {self.name}")

        body = await process.stdout.readexactly(content_length)
        return json.loads(body.decode("utf-8"))

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return

        while True:
            line = await process.stderr.readline()
            if not line:
                return
            logger.debug("MCP %s stderr: %s", self.name, line.decode(errors="replace").rstrip())

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _require_process(self) -> asyncio.subprocess.Process:
        if self._process is None:
            raise MCPClientError(f"MCP process is not running: {self.name}")
        return self._process

    def _format_tool_result(self, result: dict) -> str:
        return _format_mcp_tool_result(result)


class SSEMCPClient:
    """MCP client over SSE (Server-Sent Events) transport.

    Connects to a remote MCP server via HTTP SSE stream.  The SSE
    stream carries server→client messages; client→server requests are
    sent via HTTP POST to the endpoint URL received in the first SSE
    event.
    """

    def __init__(self, server_config: Any) -> None:
        self.server_config = server_config
        self.name = server_config.name
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._http: Optional[httpx.AsyncClient] = None
        self._request_id = 0
        self._request_lock: Optional[asyncio.Lock] = None
        self._pending: dict[int, tuple[asyncio.Event, dict]] = {}
        self._endpoint_url: str = ""
        self._tools: list[dict] = []
        self._sse_task: Optional[asyncio.Task] = None

    # ---- public API (sync, matches StdioMCPClient interface) ----

    def start(self, timeout: float = 20.0) -> list[dict]:
        if self._loop is not None:
            return self._tools

        ready = threading.Event()

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._request_lock = asyncio.Lock()
            ready.set()
            loop.run_forever()

        self._thread = threading.Thread(
            target=run_loop,
            name=f"mcp-sse-{self.name}",
            daemon=True,
        )
        self._thread.start()
        ready.wait(timeout=timeout)

        if self._loop is None:
            raise MCPClientError(f"Failed to start MCP SSE event loop: {self.name}")

        future = asyncio.run_coroutine_threadsafe(self._async_start(), self._loop)
        try:
            self._tools = future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise MCPClientError(
                f"Timed out starting MCP SSE server: {self.name}"
            ) from exc
        return self._tools

    def call_tool(
        self, tool_name: str, arguments: dict, timeout: float = 60.0
    ) -> str:
        if self._loop is None:
            self.start()
        if self._loop is None:
            raise MCPClientError(f"MCP SSE client is not running: {self.name}")

        future = asyncio.run_coroutine_threadsafe(
            self._async_call_tool(tool_name, arguments),
            self._loop,
        )
        try:
            result = future.result(timeout=timeout)
        except FutureTimeoutError as exc:
            future.cancel()
            raise MCPClientError(
                f"Timed out calling MCP SSE tool {tool_name}"
            ) from exc
        return _format_mcp_tool_result(result)

    def stop(self, timeout: float = 5.0) -> None:
        if self._loop is None:
            return

        future = asyncio.run_coroutine_threadsafe(self._async_stop(), self._loop)
        try:
            future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()

        self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=timeout)

        self._loop = None
        self._thread = None
        self._http = None
        self._request_lock = None
        self._pending = {}
        self._endpoint_url = ""
        self._tools = []
        self._sse_task = None

    # ---- async internals ----

    async def _async_start(self) -> list[dict]:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(60.0))

        sse_url = self.server_config.url
        if not sse_url:
            raise MCPClientError(
                f"SSE MCP server {self.name} has no url configured"
            )

        # Open SSE stream
        response = await self._http.send(
            self._http.build_request(
                "GET", sse_url, headers={"Accept": "text/event-stream"}
            ),
            stream=True,
        )
        response.raise_for_status()

        self._sse_task = asyncio.create_task(self._read_sse_events(response))

        # Wait for the endpoint event (first SSE message)
        self._endpoint_url = await self._wait_for_endpoint()

        # MCP handshake
        await self._sse_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "opendog", "version": "0.1.0"},
            },
        )
        await self._sse_notify("notifications/initialized", {})
        tools_result = await self._sse_request("tools/list", {})
        return tools_result.get("tools", [])

    async def _async_stop(self) -> None:
        if self._sse_task is not None:
            self._sse_task.cancel()
            try:
                await self._sse_task
            except asyncio.CancelledError:
                pass
            self._sse_task = None

        if self._http is not None:
            await self._http.aclose()
            self._http = None

        # Wake any pending requests
        for _event, response_store in self._pending.values():
            response_store["error"] = {"code": -1, "message": "Client stopped"}
            _event.set()
        self._pending.clear()

    async def _async_call_tool(
        self, tool_name: str, arguments: dict
    ) -> dict:
        return await self._sse_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments},
        )

    async def _sse_request(self, method: str, params: dict) -> dict:
        if self._request_lock is None:
            raise MCPClientError(f"MCP SSE client lock is not ready: {self.name}")

        async with self._request_lock:
            request_id = self._next_request_id()
            payload = {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }

            event = asyncio.Event()
            response_store: dict = {}
            self._pending[request_id] = (event, response_store)

            try:
                # POST the request to the message endpoint
                resp = await self._http.post(self._endpoint_url, json=payload)
                resp.raise_for_status()

                # Some SSE servers return the response in the POST body
                # rather than on the event stream.
                if resp.content:
                    try:
                        body = resp.json()
                        if isinstance(body, dict) and body.get("id") == request_id:
                            if "error" in body:
                                raise MCPClientError(
                                    f"MCP SSE request failed on {self.name}: "
                                    f"{body['error']}"
                                )
                            return body.get("result", {})
                    except (json.JSONDecodeError, ValueError):
                        pass

                # Standard path: wait for the response on the SSE stream
                await asyncio.wait_for(event.wait(), timeout=30.0)
            except asyncio.TimeoutError:
                raise MCPClientError(
                    f"Timed out waiting for SSE response: {method}"
                )
            finally:
                self._pending.pop(request_id, None)

            if "error" in response_store:
                raise MCPClientError(
                    f"MCP SSE request failed on {self.name}: "
                    f"{response_store['error']}"
                )
            return response_store.get("result", {})

    async def _sse_notify(self, method: str, params: dict) -> None:
        if self._http is None:
            raise MCPClientError(f"MCP SSE client is not running: {self.name}")

        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        resp = await self._http.post(self._endpoint_url, json=payload)
        resp.raise_for_status()

    async def _read_sse_events(self, response: httpx.Response) -> None:
        """Read SSE events from the HTTP stream indefinitely."""
        event_type = ""
        data_buf = ""

        try:
            async for line in response.aiter_lines():
                if line == "":
                    # Empty line = end of event
                    if data_buf:
                        self._handle_sse_event(event_type, data_buf)
                    event_type = ""
                    data_buf = ""
                elif line.startswith("event:"):
                    event_type = line[6:].strip()
                elif line.startswith("data:"):
                    data_buf = line[5:].strip()
                # Lines starting with ":" are comments, ignored
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug(
                "SSE stream ended for %s", self.name, exc_info=True
            )

    def _handle_sse_event(self, event_type: str, data: str) -> None:
        if event_type == "endpoint":
            endpoint = data
            if not endpoint.startswith("http") and self.server_config.url:
                endpoint = urljoin(self.server_config.url, endpoint)
            self._endpoint_url = endpoint
            self._set_endpoint_event()

        elif event_type in ("message", ""):
            try:
                message = json.loads(data)
            except json.JSONDecodeError:
                return

            msg_id = message.get("id")
            if msg_id is not None and msg_id in self._pending:
                event, response_store = self._pending[msg_id]
                response_store.update(message)
                event.set()

    async def _wait_for_endpoint(self) -> str:
        self._endpoint_ready: asyncio.Event = asyncio.Event()
        self._endpoint_value: str = ""

        try:
            await asyncio.wait_for(self._endpoint_ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            raise MCPClientError(
                f"Timed out waiting for SSE endpoint event: {self.name}"
            )
        return self._endpoint_value

    def _set_endpoint_event(self) -> None:
        ready = getattr(self, "_endpoint_ready", None)
        if ready is not None:
            self._endpoint_value = self._endpoint_url
            ready.set()

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

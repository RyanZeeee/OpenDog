from __future__ import annotations

import concurrent.futures
import logging
import threading
from typing import Any

from opendog.tools.base import FunctionTool
from opendog.tools.mcp.client import (
    MCPClient,
    MCPClientError,
    SSEMCPClient,
    StdioMCPClient,
)
from opendog.tools.mcp.tool import MCPRemoteTool
from opendog.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class MCPManager:
    def __init__(self, server_configs: dict[str, Any], registry: ToolRegistry) -> None:
        self.server_configs = server_configs
        self.registry = registry
        self.clients: dict[str, MCPClient] = {}
        self.server_tools: dict[str, list[str]] = {}
        self._lock = threading.Lock()
        self._startup_futures: dict[str, concurrent.futures.Future] = {}
        self._startup_executor: concurrent.futures.ThreadPoolExecutor | None = None

    def register_management_tools(self) -> None:
        self.registry.register(self._make_list_servers_tool(), source="builtin")
        self.registry.register(self._make_start_server_tool(), source="builtin")
        self.registry.register(self._make_stop_server_tool(), source="builtin")

    def start_enabled_servers(self) -> None:
        for name, config in self.server_configs.items():
            if config.enabled:
                self.start_server(name, requested_by_agent=False)

    def start_enabled_servers_background(self) -> list[str]:
        names = [
            name
            for name, config in self.server_configs.items()
            if config.enabled
        ]
        if not names:
            return []

        self._startup_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=min(len(names), 8)
        )
        for name in names:
            future = self._startup_executor.submit(self._start_server_worker, name)
            self._startup_futures[name] = future

        return names

    def _start_server_worker(self, name: str) -> None:
        try:
            result = self.start_server(name, requested_by_agent=False)
            logger.info(
                "MCP server '%s' started: %d tools",
                name,
                len(result.get("tools", [])),
            )
        except Exception as exc:
            logger.warning("MCP server '%s' failed to start: %s", name, exc)

    def startup_done_count(self) -> tuple[int, int]:
        if not self._startup_futures:
            return (0, 0)
        done = sum(1 for f in self._startup_futures.values() if f.done())
        return (done, len(self._startup_futures))

    def startup_in_progress(self) -> bool:
        done, total = self.startup_done_count()
        return done < total

    def list_servers(self) -> list[dict]:
        with self._lock:
            servers = []
            for name, config in self.server_configs.items():
                servers.append(
                    {
                        "name": name,
                        "description": config.description,
                        "type": config.type,
                        "enabled": config.enabled,
                        "agent_managed": config.agent_managed,
                        "running": name in self.clients,
                        "tools": self.server_tools.get(name, []),
                    }
                )
            return servers

    def start_server(self, name: str, requested_by_agent: bool = True) -> dict:
        with self._lock:
            config = self.server_configs.get(name)
            if config is None:
                return {"ok": False, "error": f"Unknown MCP server: {name}"}

            if requested_by_agent and not config.agent_managed:
                return {
                    "ok": False,
                    "error": f"MCP server is not agent-managed: {name}",
                }

            if name in self.clients:
                return {
                    "ok": True,
                    "message": f"MCP server already running: {name}",
                    "tools": self.server_tools.get(name, []),
                }

        # Network / subprocess I/O outside the lock so concurrent starts don't block each other.
        try:
            runtime_config = self._with_server_name(config, name)
            client = self._create_client(runtime_config)
            tool_definitions = client.start()
        except (MCPClientError, OSError, TimeoutError) as exc:
            return {"ok": False, "error": f"Failed to start MCP server {name}: {exc}"}

        with self._lock:
            tool_names = []
            for tool_definition in tool_definitions:
                tool = MCPRemoteTool(client, tool_definition)
                self.registry.register(tool, source="mcp", provider=name)
                tool_names.append(tool.name)

            self.clients[name] = client
            self.server_tools[name] = tool_names

        return {
            "ok": True,
            "message": f"Started MCP server: {name}",
            "tools": tool_names,
        }

    def stop_server(self, name: str, requested_by_agent: bool = True) -> dict:
        with self._lock:
            config = self.server_configs.get(name)
            if config is None:
                return {"ok": False, "error": f"Unknown MCP server: {name}"}

            if requested_by_agent and not config.agent_managed:
                return {
                    "ok": False,
                    "error": f"MCP server is not agent-managed: {name}",
                }

            client = self.clients.pop(name, None)
            if client is None:
                return {"ok": True, "message": f"MCP server is already stopped: {name}"}

            removed_tools = self.registry.unregister_by_source_provider("mcp", name)
            self.server_tools.pop(name, None)

        client.stop()
        return {
            "ok": True,
            "message": f"Stopped MCP server: {name}",
            "removed_tools": removed_tools,
        }

    def _make_list_servers_tool(self) -> FunctionTool:
        async def list_servers(session: Any) -> str:
            return session.dumps_tool_result(self.list_servers())

        return FunctionTool(
            name="mcp_list_servers",
            description="查看配置中可用的 MCP 服务器、运行状态，以及已暴露的工具。",
            parameters={"type": "object", "properties": {}},
            function=list_servers,
        )

    def _make_start_server_tool(self) -> FunctionTool:
        async def start_server(server_name: str, session: Any) -> str:
            return session.dumps_tool_result(self.start_server(server_name))

        return FunctionTool(
            name="mcp_start_server",
            description="启动一个配置中允许 Agent 管理的 MCP 服务器。",
            parameters={
                "type": "object",
                "properties": {
                    "server_name": {
                        "type": "string",
                        "description": "要启动的 MCP 服务器名称。",
                    }
                },
                "required": ["server_name"],
            },
            function=start_server,
        )

    def _make_stop_server_tool(self) -> FunctionTool:
        async def stop_server(server_name: str, session: Any) -> str:
            return session.dumps_tool_result(self.stop_server(server_name))

        return FunctionTool(
            name="mcp_stop_server",
            description="关闭一个配置中允许 Agent 管理的 MCP 服务器，并注销它暴露的工具。",
            parameters={
                "type": "object",
                "properties": {
                    "server_name": {
                        "type": "string",
                        "description": "要关闭的 MCP 服务器名称。",
                    }
                },
                "required": ["server_name"],
            },
            function=stop_server,
        )

    def _create_client(self, config: Any) -> MCPClient:
        if config.type == "stdio":
            return StdioMCPClient(config)
        if config.type in ("sse", "streamable-http"):
            return SSEMCPClient(config)
        raise MCPClientError(f"Unsupported MCP server type: {config.type}")

    def _with_server_name(self, config: Any, name: str) -> Any:
        if hasattr(config, "model_copy"):
            return config.model_copy(update={"name": name})
        config.name = name
        return config

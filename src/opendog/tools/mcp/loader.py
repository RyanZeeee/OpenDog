from __future__ import annotations

from typing import Any

from opendog.tools.mcp.manager import MCPManager
from opendog.tools.registry import ToolRegistry


def load_mcp_tools(mcp_servers: dict[str, Any], registry: ToolRegistry) -> MCPManager:
    manager = MCPManager(mcp_servers, registry)
    manager.register_management_tools()
    # Defer server startup to TuiChatLoop so the TUI appears immediately.
    registry._mcp_manager = manager
    return manager

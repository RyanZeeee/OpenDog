from __future__ import annotations

import asyncio
from typing import Any

from opendog.tools.base import BaseTool
from opendog.tools.mcp.client import MCPClient


class MCPRemoteTool(BaseTool):
    def __init__(self, client: MCPClient, tool_definition: dict) -> None:
        self.client = client
        self.remote_name = tool_definition["name"]
        self.name = tool_definition["name"]
        self.description = tool_definition.get("description", "")
        self.parameters = tool_definition.get(
            "inputSchema",
            {"type": "object", "properties": {}},
        )

    async def execute(self, session: Any, **kwargs: Any) -> str:
        return await asyncio.to_thread(self.client.call_tool, self.remote_name, kwargs)

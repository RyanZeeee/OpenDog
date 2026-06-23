from __future__ import annotations

from typing import Any

from opendog.tools.base import tool


@tool(
    name="list_tools",
    description="List currently available tools grouped by source. Useful when answering questions about tool capabilities.",
    parameters={"type": "object", "properties": {}},
)
async def list_tools(session: Any) -> str:
    return session.dumps_tool_result(session.tools.list_tools_by_source())

from __future__ import annotations

from typing import Any

from opendog.tools.base import tool


@tool(
    name="list_tools",
    description="按来源分组查看当前可用工具，适合回答用户关于工具能力的问题。",
    parameters={"type": "object", "properties": {}},
)
async def list_tools(session: Any) -> str:
    return session.dumps_tool_result(session.tools.list_tools_by_source())

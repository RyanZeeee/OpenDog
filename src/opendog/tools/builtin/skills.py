from __future__ import annotations

from typing import Any

from opendog.tools.base import tool


@tool(
    name="list_skills",
    description="List the skills available in the current session.",
    parameters={"type": "object", "properties": {}},
)
async def list_skills(session: Any) -> str:
    return session.dumps_tool_result(session.skills.list_skills())

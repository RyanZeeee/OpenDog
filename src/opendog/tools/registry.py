from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from opendog.tools.base import BaseTool


@dataclass
class ToolInfo:
    name: str
    description: str
    source: str
    provider: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._tool_info: dict[str, ToolInfo] = {}
        self._lock = threading.Lock()
        self._mcp_manager: Any = None

    def register(
        self,
        tool: BaseTool,
        source: str = "unknown",
        provider: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            self._tools[tool.name] = tool
            self._tool_info[tool.name] = ToolInfo(
                name=tool.name,
                description=tool.description,
                source=source,
                provider=provider,
                metadata=metadata or {},
            )

    def register_many(
        self,
        tools: list[BaseTool],
        source: str = "unknown",
        provider: Optional[str] = None,
    ) -> None:
        with self._lock:
            for tool in tools:
                self._tools[tool.name] = tool
                self._tool_info[tool.name] = ToolInfo(
                    name=tool.name,
                    description=tool.description,
                    source=source,
                    provider=provider,
                    metadata={},
                )

    def get(self, name: str) -> Optional[BaseTool]:
        with self._lock:
            return self._tools.get(name)

    def unregister(self, name: str) -> None:
        with self._lock:
            self._tools.pop(name, None)
            self._tool_info.pop(name, None)

    def unregister_by_source_provider(self, source: str, provider: str) -> list[str]:
        with self._lock:
            names = [
                name
                for name, info in self._tool_info.items()
                if info.source == source and info.provider == provider
            ]
            for name in names:
                self._tools.pop(name, None)
                self._tool_info.pop(name, None)
            return names

    def names(self) -> list[str]:
        with self._lock:
            return list(self._tools.keys())

    def list_tools(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "name": info.name,
                    "description": info.description,
                    "source": info.source,
                    "provider": info.provider,
                }
                for info in self._tool_info.values()
            ]

    def set_tool_source(
        self,
        name: str,
        source: str,
        provider: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        with self._lock:
            info = self._tool_info.get(name)
            if info is None:
                return
            info.source = source
            info.provider = provider
            if metadata is not None:
                info.metadata = metadata

    def list_tools_by_source(self) -> dict[str, list[dict]]:
        with self._lock:
            grouped: dict[str, list[dict]] = {}
            for info in self._tool_info.values():
                grouped.setdefault(info.source, []).append(
                    {
                        "name": info.name,
                        "description": info.description,
                        "source": info.source,
                        "provider": info.provider,
                    }
                )
            return grouped

    def get_tool_schemas(self) -> list[dict]:
        with self._lock:
            return [tool.get_tool_schema() for tool in self._tools.values()]

    async def execute_tool(self, name: str, session: Any, **kwargs: Any) -> str:
        with self._lock:
            tool = self._tools.get(name)
        if tool is None:
            return session.dumps_tool_result(
                {"ok": False, "error": f"Unknown tool: {name}"}
            )
        return await tool.execute(session=session, **kwargs)

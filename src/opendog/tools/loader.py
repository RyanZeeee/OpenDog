from __future__ import annotations

from pathlib import Path
from typing import Any, Union

from opendog.tools.builtin import BUILTIN_TOOLS
from opendog.tools.info import list_tools
from opendog.tools.mcp.loader import load_mcp_tools
from opendog.tools.plugins.loader import load_plugin_tools
from opendog.tools.registry import ToolRegistry


def load_tool_registry(config: Any, workspace_root: Union[str, Path]) -> ToolRegistry:
    registry = ToolRegistry()
    root = Path(workspace_root)
    tool_config = config.tools

    if tool_config.builtin.enabled:
        registry.register_many(BUILTIN_TOOLS, source="builtin")

    load_plugin_tools(tool_config.plugins, root, registry)
    load_mcp_tools(config.mcpServers, registry)
    registry.register(list_tools, source="builtin")
    return registry

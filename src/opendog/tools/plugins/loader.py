from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from opendog.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def load_plugin_tools(plugin_config: Any, workspace_root: Path, registry: ToolRegistry) -> None:
    if not plugin_config.enabled:
        return

    for configured_path in plugin_config.paths:
        plugin_root = _resolve_plugin_path(workspace_root, Path(configured_path))
        if not plugin_root.exists():
            continue

        for plugin_file in _discover_plugin_files(plugin_root):
            _load_single_plugin(plugin_file, registry)


def _resolve_plugin_path(workspace_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return workspace_root / path


def _discover_plugin_files(plugin_root: Path) -> list[Path]:
    direct_plugin = plugin_root / "plugin.py"
    if direct_plugin.exists():
        return [direct_plugin]

    return [
        plugin_dir / "plugin.py"
        for plugin_dir in plugin_root.iterdir()
        if plugin_dir.is_dir() and (plugin_dir / "plugin.py").exists()
    ]


def _load_single_plugin(plugin_file: Path, registry: ToolRegistry) -> None:
    try:
        module = _import_plugin_module(plugin_file)
        register_tools = getattr(module, "register_tools", None)
        if not callable(register_tools):
            logger.warning("Plugin %s has no register_tools(registry) function.", plugin_file)
            return

        before = set(registry.names())
        register_tools(registry)
        after = set(registry.names())
        for tool_name in after - before:
            registry.set_tool_source(
                tool_name,
                source="plugin",
                provider=plugin_file.parent.name,
            )
    except Exception as exc:
        logger.warning("Failed to load tool plugin %s: %s", plugin_file, exc)


def _import_plugin_module(plugin_file: Path) -> ModuleType:
    module_name = f"opendog_plugin_{plugin_file.parent.name}_{abs(hash(str(plugin_file)))}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import plugin file: {plugin_file}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

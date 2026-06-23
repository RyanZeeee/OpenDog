from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from opendog.core.agent import Agent, AgentSession

PIXEL_LOGO = [
    "..BBBBBBB..",
    ".BBBBBBBBB.",
    "BBBBBABBBBB",
    "BBBBBABBBBB",
    "BBBEBABEBBB",
    "BBBAAAAABBB",
    "BBBAAEAABBB",
    "..BAAAAABA.",
    "..AAAAAAAA.",
    "..AA....AB.",
    "..AA....AA.",
]


@dataclass
class StartupStatus:
    version: str
    agent_name: str
    model: str
    working_dir: Path
    workspace_root: Path
    skill_count: int
    tool_count: int
    tool_sources: dict[str, int]
    mcp_configured: int


def collect_startup_status(
    context: object,
    agent: Agent,
    session: AgentSession,
) -> StartupStatus:
    tool_groups = session.tools.list_tools_by_source()
    tool_sources = {source: len(tools) for source, tools in tool_groups.items()}
    llm_config = context.config.llm
    return StartupStatus(
        version=get_project_version(),
        agent_name=agent.agent_def.name,
        model=build_model_label(llm_config.provider, llm_config.model),
        working_dir=context.working_dir,
        workspace_root=context.workspace_root,
        skill_count=len(session.skills.list_skills()["skills"]),
        tool_count=sum(tool_sources.values()),
        tool_sources=tool_sources,
        mcp_configured=len(context.config.mcpServers),
    )


def build_model_label(provider: str, model: str) -> str:
    if not provider or provider == "openai" or "/" in model:
        return model
    return f"{provider}/{model}"


def get_project_version() -> str:
    try:
        return version("opendog")
    except PackageNotFoundError:
        return read_pyproject_version()


def read_pyproject_version() -> str:
    current = Path(__file__).resolve()
    for parent in current.parents:
        pyproject = parent / "pyproject.toml"
        if pyproject.exists():
            match = re.search(
                r'^version\s*=\s*"([^"]+)"',
                pyproject.read_text(encoding="utf-8"),
                re.MULTILINE,
            )
            if match:
                return match.group(1)
    return "unknown"

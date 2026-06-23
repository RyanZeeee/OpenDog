from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

from opendog.utils.def_loader import parse_definition


@dataclass
class AgentDef:
    id: str
    name: str
    description: str
    system_prompt: str
    path: Path
    agent_dir: Path
    allowed_skills: Optional[list[str]] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class AgentSummary:
    id: str
    name: str
    description: str
    path: Path


def discover_agents(agents_dir: Union[str, Path]) -> list[AgentSummary]:
    root = Path(agents_dir)
    if not root.exists():
        return []

    agents: list[AgentSummary] = []
    for agent_file in sorted(root.glob("*/AGENT.md")):
        metadata, _body = parse_definition(agent_file.read_text(encoding="utf-8"))
        agent_id = agent_file.parent.name
        agents.append(
            AgentSummary(
                id=agent_id,
                name=str(metadata.get("name") or agent_id),
                description=str(metadata.get("description") or ""),
                path=agent_file,
            )
        )
    return agents


def load_agent_definition(path: Union[str, Path]) -> AgentDef:
    agent_path = Path(path)
    metadata, body = parse_definition(agent_path.read_text(encoding="utf-8"))

    soul_path = agent_path.parent / "SOUL.md"
    if soul_path.exists():
        soul = soul_path.read_text(encoding="utf-8").strip()
        if soul:
            body = f"{body.strip()}\n\n{soul}"

    allowed_skills = load_agent_skill_names(agent_path.parent)
    agent_id = agent_path.parent.name
    name = str(metadata.get("name") or agent_id)
    description = str(metadata.get("description") or "")
    return AgentDef(
        id=agent_id,
        name=name,
        description=description,
        system_prompt=body.strip(),
        path=agent_path,
        agent_dir=agent_path.parent,
        allowed_skills=allowed_skills,
        metadata=metadata,
    )


def load_agent_skill_names(agent_dir: Path) -> Optional[list[str]]:
    skills_path = agent_dir / "skills.txt"
    if not skills_path.exists():
        return None

    names: list[str] = []
    for line in skills_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        names.append(line)
    return names

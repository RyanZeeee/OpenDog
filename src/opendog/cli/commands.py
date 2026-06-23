"""斜杠命令系统 —— 在用户输入进入 LLM 之前拦截并本地执行。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from opendog.core.agent_loader import discover_agents, load_agent_definition


class Command:
    name: str = ""
    aliases: list[str] = []
    description: str = ""

    async def execute(self, args: str, session, context) -> str:
        raise NotImplementedError


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, cmd: Command) -> None:
        for key in [cmd.name, *cmd.aliases]:
            self._commands[key] = cmd

    def dispatch(self, text: str, session, context) -> Optional[str]:
        if not text.startswith("/"):
            return None
        body = text[1:]
        if not body:
            return None

        parts = body.split(maxsplit=1)
        name = parts[0]
        args = parts[1] if len(parts) > 1 else ""

        cmd = self._commands.get(name)
        if cmd is None:
            return None
        return cmd.execute(args, session, context)

    def list_commands(self) -> list[Command]:
        seen: set[str] = set()
        result: list[Command] = []
        for cmd in self._commands.values():
            if cmd.name not in seen:
                seen.add(cmd.name)
                result.append(cmd)
        result.sort(key=lambda c: c.name)
        return result

    @classmethod
    def with_builtins(cls, skills_dir: Path) -> "CommandRegistry":
        registry = cls()
        registry.register(HelpCommand(registry))
        registry.register(SessionCommand())
        registry.register(SkillsCommand(skills_dir))
        registry.register(AgentCommand())
        registry.register(McpCommand())
        registry.register(CompactCommand())
        return registry


# ── 内建命令 ──────────────────────────────────────────────

@dataclass
class HelpCommand(Command):
    registry: CommandRegistry

    def __post_init__(self):
        self.name = "help"
        self.aliases = []
        self.description = "列出所有可用命令"

    async def execute(self, args: str, session, context) -> str:
        lines = ["可用命令：", ""]
        for cmd in self.registry.list_commands():
            aliases_str = f" ({', '.join('/' + a for a in cmd.aliases)})" if cmd.aliases else ""
            lines.append(f"  /{cmd.name}{aliases_str} — {cmd.description}")
        return "\n".join(lines)


@dataclass
class SessionCommand(Command):
    def __post_init__(self):
        self.name = "session"
        self.aliases = []
        self.description = "显示当前会话信息"

    async def execute(self, args: str, session, context) -> str:
        state = session.state
        short_id = state.session_id[:8]
        created = state.created_at[:19].replace("T", " ")
        lines = [
            f"会话 ID     {short_id}",
            f"Agent       {state.agent_name}",
            f"消息数      {len(state.messages)}",
            f"创建时间    {created}",
        ]
        return "\n".join(lines)


@dataclass
class SkillsCommand(Command):
    skills_dir: Path

    def __post_init__(self):
        self.name = "skills"
        self.aliases = []
        self.description = "列出所有可用 skill"

    async def execute(self, args: str, session, context) -> str:
        skills = getattr(session, "skills", None)
        if skills is None:
            from opendog.core.skill_registry import SkillRegistry
            skills = SkillRegistry.load(self.skills_dir)
        if not skills._skills:
            return "暂无可用 skill"
        lines = ["可用 Skills：", ""]
        for skill in skills._skills.values():
            lines.append(f"  {skill.name}")
        return "\n".join(lines)


@dataclass
class AgentCommand(Command):
    def __post_init__(self):
        self.name = "agent"
        self.aliases = []
        self.description = "列出/切换当前 Agent（/agent [agent_id]）"

    async def execute(self, args: str, session, context) -> str:
        agents_dir = context.workspace_root / context.config.paths.agents_dir
        agents = discover_agents(agents_dir)
        current_def = getattr(session, "current_agent_def", session.agent.agent_def)
        current = getattr(current_def, "id", current_def.name)

        if not args.strip():
            lines = [f"当前 Agent：{current}", "", "可用 Agent："]
            if not agents:
                lines.append("  暂无可用 Agent")
                return "\n".join(lines)
            for item in agents:
                marker = "*" if item.id == current else " "
                description = f" — {item.description}" if item.description else ""
                lines.append(f"  {marker} {item.id}{description}")
            return "\n".join(lines)

        target_id = args.strip().split()[0]
        agent_path = agents_dir / target_id / "AGENT.md"
        if not agent_path.exists():
            return f"Agent 不存在：{target_id}"

        agent_def = load_agent_definition(agent_path)
        session.switch_agent(agent_def)
        return (
            f"已切换 Agent：{agent_def.id}\n"
            "当前会话记录保持不变。"
        )


@dataclass
class McpCommand(Command):
    def __post_init__(self):
        self.name = "mcp"
        self.aliases = []
        self.description = "列出/切换 MCP 配置（/mcp [name on|off]）"

    async def execute(self, args: str, session, context) -> str:
        config_path = context.workspace_root / "config.user.yaml"
        servers = context.config.mcpServers

        if not args:
            if not servers:
                return "暂无 MCP 配置"
            lines = ["MCP 配置：", ""]
            for name, srv in servers.items():
                status = "启用" if srv.enabled else "关闭"
                lines.append(f"  {name} [{status}] — {srv.description}")
            return "\n".join(lines)

        parts = args.split()
        if len(parts) != 2 or parts[1] not in ("on", "off"):
            return "用法：/mcp <name> on|off"

        name, action = parts[0], parts[1]
        if name not in servers:
            return f"MCP 配置 '{name}' 不存在"

        enabled = action == "on"
        raw = config_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw) or {}
        if "mcpServers" not in data or name not in data["mcpServers"]:
            return f"MCP 配置 '{name}' 在 YAML 中不存在"

        data["mcpServers"][name]["enabled"] = enabled
        config_path.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")

        # 同步到内存
        servers[name].enabled = enabled
        status = "启用" if enabled else "关闭"
        return f"MCP '{name}' 已{status}（下次启动生效）"


@dataclass
class CompactCommand(Command):
    def __post_init__(self):
        self.name = "compact"
        self.aliases = []
        self.description = "强制压缩当前上下文"

    async def execute(self, args: str, session, context) -> str:
        state = session.state
        if len(state.messages) < 3:
            return "当前历史对话较少，无需压缩"

        status = state.compact_if_needed(force=True)
        if status == "overflow":
            return "上下文已压缩\n⚠ 上下文仍然超过上限，请考虑开启新对话。"
        return "上下文已压缩"

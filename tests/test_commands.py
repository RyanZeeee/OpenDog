import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opendog.cli.commands import AgentCommand, SkillsCommand
from opendog.core.agent_loader import AgentDef
from opendog.core.skill_registry import SkillRegistry


class FakeState:
    def __init__(self) -> None:
        self.session_id = "session-1"
        self.messages = [{"role": "user", "content": "旧消息"}]
        self.agent_name = "Beagle"
        self.system_prompt = "old"
        self.store = None

    def set_system_prompt(self, value: str) -> None:
        self.system_prompt = value


class FakeSession:
    def __init__(self, skills_dir: Path) -> None:
        self.state = FakeState()
        self.skills_dir = skills_dir
        self.skills = SkillRegistry.load(skills_dir)
        self.agent = SimpleNamespace(
            agent_def=AgentDef(
                id="Beagle",
                name="Beagle",
                description="默认助手",
                system_prompt="beagle prompt",
                path=Path("Beagle/AGENT.md"),
                agent_dir=Path("Beagle"),
                allowed_skills=None,
            ),
            skills_dir=skills_dir,
        )

    def switch_agent(self, agent_def: AgentDef) -> None:
        self.agent.agent_def = agent_def
        self.state.agent_name = agent_def.name
        self.skills = SkillRegistry.load(
            self.skills_dir,
            allowed_names=agent_def.allowed_skills,
        )
        self.state.set_system_prompt(agent_def.system_prompt)


def write_skill(root: Path, name: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill\n---\n\n正文。\n",
        encoding="utf-8",
    )


class CommandTest(unittest.IsolatedAsyncioTestCase):
    async def test_agent_command_lists_and_switches_without_clearing_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            agents_dir = workspace / "agents"
            skills_dir = workspace / "skills"
            (agents_dir / "Beagle").mkdir(parents=True)
            (agents_dir / "Designer").mkdir(parents=True)
            skills_dir.mkdir()
            write_skill(skills_dir, "docx")
            write_skill(skills_dir, "ui-ux-pro-max")
            (agents_dir / "Beagle" / "AGENT.md").write_text(
                "---\nname: Beagle\ndescription: 默认助手\n---\n\nBeagle prompt\n",
                encoding="utf-8",
            )
            (agents_dir / "Designer" / "AGENT.md").write_text(
                "---\nname: Designer\ndescription: 设计助手\n---\n\nDesigner prompt\n",
                encoding="utf-8",
            )
            (agents_dir / "Designer" / "skills.txt").write_text(
                "ui-ux-pro-max\n",
                encoding="utf-8",
            )
            context = SimpleNamespace(
                workspace_root=workspace,
                config=SimpleNamespace(paths=SimpleNamespace(agents_dir=Path("agents"))),
            )
            session = FakeSession(skills_dir)
            command = AgentCommand()
            command.__post_init__()

            listing = await command.execute("", session, context)
            self.assertIn("当前 Agent：Beagle", listing)
            self.assertIn("Designer — 设计助手", listing)

            before_messages = session.state.messages
            result = await command.execute("Designer", session, context)

            self.assertIn("已切换 Agent：Designer", result)
            self.assertEqual(session.state.session_id, "session-1")
            self.assertIs(session.state.messages, before_messages)
            self.assertEqual(session.state.agent_name, "Designer")
            self.assertEqual(list(session.skills._skills), ["ui-ux-pro-max"])

    async def test_skills_command_uses_current_session_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            write_skill(skills_dir, "docx")
            write_skill(skills_dir, "pptx")
            session = FakeSession(skills_dir)
            session.skills = SkillRegistry.load(skills_dir, allowed_names=["pptx"])
            command = SkillsCommand(skills_dir)
            command.__post_init__()

            result = await command.execute("", session, object())

            self.assertIn("pptx", result)
            self.assertNotIn("docx", result)


if __name__ == "__main__":
    unittest.main()

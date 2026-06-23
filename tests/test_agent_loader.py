import tempfile
import unittest
from pathlib import Path

from opendog.core.agent_loader import discover_agents, load_agent_definition


class AgentLoaderTest(unittest.TestCase):
    def test_load_agent_definition_reads_soul_and_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agent_dir = Path(tmp) / "Designer"
            agent_dir.mkdir()
            (agent_dir / "AGENT.md").write_text(
                """---
name: Designer
description: UI 设计助手
---

你是 Designer。
""",
                encoding="utf-8",
            )
            (agent_dir / "SOUL.md").write_text("你说话简洁。", encoding="utf-8")
            (agent_dir / "skills.txt").write_text(
                "# allowed skills\nui-ux-pro-max\npptx\n",
                encoding="utf-8",
            )

            agent_def = load_agent_definition(agent_dir / "AGENT.md")

            self.assertEqual(agent_def.id, "Designer")
            self.assertEqual(agent_def.name, "Designer")
            self.assertEqual(agent_def.description, "UI 设计助手")
            self.assertIn("你是 Designer。", agent_def.system_prompt)
            self.assertIn("你说话简洁。", agent_def.system_prompt)
            self.assertEqual(agent_def.allowed_skills, ["ui-ux-pro-max", "pptx"])

    def test_discover_agents_reads_agent_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents_dir = Path(tmp)
            beagle_dir = agents_dir / "Beagle"
            beagle_dir.mkdir()
            (beagle_dir / "AGENT.md").write_text(
                """---
name: Beagle
description: 默认助手
---

正文。
""",
                encoding="utf-8",
            )

            agents = discover_agents(agents_dir)

            self.assertEqual(len(agents), 1)
            self.assertEqual(agents[0].id, "Beagle")
            self.assertEqual(agents[0].name, "Beagle")
            self.assertEqual(agents[0].description, "默认助手")


if __name__ == "__main__":
    unittest.main()

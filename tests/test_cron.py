import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from opendog.core.cron.definition import CronDef
from opendog.core.cron.loader import disable_cron, discover_crons
from opendog.core.cron.runner import CronRunner
from opendog.core.cron.scheduler import CronScheduler, cron_matches, schedule_respects_min_interval
from opendog.interfaces.feishu.state import FeishuState


class CronLoaderTest(unittest.TestCase):
    def test_load_cron_definition_with_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cron_dir = root / "morning-news"
            cron_dir.mkdir()
            (cron_dir / "CRON.md").write_text(
                """---
name: Morning News
description: 每天早上总结新闻
schedule: "0 9 * * *"
---

总结新闻。
""",
                encoding="utf-8",
            )

            crons = discover_crons(root, default_agent="Beagle")

            self.assertEqual(len(crons), 1)
            cron = crons[0]
            self.assertEqual(cron.id, "morning-news")
            self.assertEqual(cron.agent, "Beagle")
            self.assertTrue(cron.enabled)
            self.assertFalse(cron.one_off)
            self.assertEqual(cron.min_interval_minutes, 5)
            self.assertEqual(cron.deliver_to, {})
            self.assertEqual(cron.prompt, "总结新闻。")

    def test_disable_cron_sets_enabled_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cron_dir = root / "one-off"
            cron_dir.mkdir()
            cron_file = cron_dir / "CRON.md"
            cron_file.write_text(
                """---
name: One Off
schedule: "0 9 * * *"
enabled: true
one_off: true
---

提醒我。
""",
                encoding="utf-8",
            )

            cron = discover_crons(root, default_agent="Beagle")[0]
            disable_cron(cron)
            reloaded = discover_crons(root, default_agent="Beagle")[0]

            self.assertFalse(reloaded.enabled)
            self.assertEqual(reloaded.prompt, "提醒我。")


class CronSchedulerTest(unittest.TestCase):
    def test_cron_matches_current_local_time_fields(self) -> None:
        now = datetime(2026, 6, 19, 9, 30)

        self.assertTrue(cron_matches("30 9 * * *", now))
        self.assertTrue(cron_matches("*/10 9 * * *", now))
        self.assertTrue(cron_matches("30 9 * * 5", now))
        self.assertFalse(cron_matches("31 9 * * *", now))

    def test_min_interval_validation(self) -> None:
        self.assertFalse(schedule_respects_min_interval("* * * * *", 5))
        self.assertFalse(schedule_respects_min_interval("*/4 * * * *", 5))
        self.assertTrue(schedule_respects_min_interval("*/5 * * * *", 5))
        self.assertTrue(schedule_respects_min_interval("0 9 * * *", 5))

    def test_due_crons_do_not_repeat_same_minute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cron_dir = root / "job"
            cron_dir.mkdir()
            (cron_dir / "CRON.md").write_text(
                """---
name: Job
schedule: "30 9 * * *"
---

运行。
""",
                encoding="utf-8",
            )
            crons = discover_crons(root, default_agent="Beagle")
            scheduler = CronScheduler(root / ".runtime" / "cron_state.json")
            now = datetime(2026, 6, 19, 9, 30)

            due = scheduler.due_crons(crons, now)
            self.assertEqual([item.cron.id for item in due], ["job"])

            scheduler.mark_ran("job", due[0].run_minute)
            self.assertEqual(scheduler.due_crons(crons, now), [])


class FakeFeishuClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_text_to_chat(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


class CronRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_deliver_uses_default_feishu_chat_id_from_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            FeishuState.from_workspace(workspace_root).remember_default_chat("oc_default")
            client = FakeFeishuClient()
            runner = CronRunner(
                context=SimpleNamespace(workspace_root=workspace_root),
                agent=SimpleNamespace(),
                session_store=SimpleNamespace(),
                feishu_client=client,
            )
            cron = CronDef(
                id="job",
                name="Job",
                description="",
                agent="Beagle",
                schedule="0 9 * * *",
                enabled=True,
                one_off=False,
                min_interval_minutes=5,
                deliver_to={"type": "feishu"},
                prompt="运行。",
                path=workspace_root / "crons" / "job" / "CRON.md",
            )

            await runner.deliver(cron, "完成")

            self.assertEqual(client.sent, [("oc_default", "完成")])


if __name__ == "__main__":
    unittest.main()

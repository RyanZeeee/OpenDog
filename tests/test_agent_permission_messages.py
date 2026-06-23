from pathlib import Path
import unittest

from opendog.core.agent import AgentSession
from opendog.core.permissions import PermissionManager


class AgentPermissionMessageTest(unittest.IsolatedAsyncioTestCase):
    async def test_shell_permission_denial_returns_clear_model_message(self) -> None:
        session = object.__new__(AgentSession)
        session.permissions = PermissionManager(
            working_dir=Path("/Users/example/opendog-project"),
            workspace_root=Path("/Users/example/opendog-engine/workspace"),
            skill_roots=[Path("/Users/example/opendog-engine/workspace/skills")],
        )

        async def deny(_request):
            return "deny"

        session.permission_handler = deny

        allowed, reason, extra_roots, include_user_home = await session.approve_shell_command(
            "ls /Users/example/Desktop"
        )

        self.assertFalse(allowed)
        self.assertEqual(extra_roots, [])
        self.assertFalse(include_user_home)
        self.assertIn("路径超出了项目边界", reason)
        self.assertIn("路径不清晰", reason)
        self.assertIn("不要换路径、换命令或反复申请", reason)


if __name__ == "__main__":
    unittest.main()

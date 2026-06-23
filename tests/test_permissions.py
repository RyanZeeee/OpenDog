from pathlib import Path
import unittest

from opendog.core.permissions import PermissionManager


class PermissionManagerShellParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.permissions = PermissionManager(
            working_dir=Path("/Users/example/opendog-project"),
            workspace_root=Path("/Users/example/opendog-engine/workspace"),
            skill_roots=[Path("/Users/example/opendog-engine/workspace/skills")],
        )

    def test_keeps_semicolons_inside_single_quoted_python_code(self) -> None:
        command = "python3 -c 'import sys; print(123); print(sys.version)'"

        self.assertEqual(
            self.permissions.shell_command_segments(command),
            [command],
        )
        self.assertEqual(self.permissions.evaluate_shell(command).action, "allow")

    def test_splits_shell_operators_outside_quotes(self) -> None:
        command = "echo before && python3 -c 'print(1); print(2)' && echo after"

        self.assertEqual(
            self.permissions.shell_command_segments(command),
            ["echo before", "python3 -c 'print(1); print(2)'", "echo after"],
        )
        self.assertEqual(self.permissions.evaluate_shell(command).action, "allow")

    def test_allows_unclosed_quotes(self) -> None:
        decision = self.permissions.evaluate_shell('pip install "markitdown[pptx] -q')

        self.assertEqual(decision.action, "allow")

    def test_allows_command_substitution(self) -> None:
        decision = self.permissions.evaluate_shell("echo $(pwd)")

        self.assertEqual(decision.action, "allow")

    def test_allows_global_npm_install_when_no_outside_path_is_visible(self) -> None:
        decision = self.permissions.evaluate_shell("npm install -g pptxgenjs")

        self.assertEqual(decision.action, "allow")

    def test_denies_shell_paths_outside_working_dir(self) -> None:
        decision = self.permissions.evaluate_shell("ls /Users/example/Desktop")

        self.assertEqual(decision.action, "deny")
        self.assertIsNotNone(decision.request)
        self.assertEqual(decision.request.reason, "命令访问了允许目录外的路径。")

    def test_osascript_requires_permission_even_without_literal_path(self) -> None:
        command = (
            "osascript -e 'tell application \"Finder\" to delete file "
            '"GoGoMath-儿童数学APP_HATAKE1996s-站酷ZCOOL.pdf" of desktop\''
        )

        decision = self.permissions.evaluate_shell(command)

        self.assertEqual(decision.action, "deny")
        self.assertIsNotNone(decision.request)
        self.assertEqual(
            decision.request.reason,
            "osascript 可能通过系统应用操作允许目录外的资源。",
        )

    def test_allows_shell_paths_inside_working_dir(self) -> None:
        decision = self.permissions.evaluate_shell("rm -rf /Users/example/opendog-project/build")

        self.assertEqual(decision.action, "allow")

    def test_denies_read_outside_working_dir(self) -> None:
        decision = self.permissions.evaluate_read_path("/Users/example/Desktop/file.txt")

        self.assertEqual(decision.action, "deny")
        self.assertIsNotNone(decision.request)
        self.assertEqual(decision.request.reason, "目标路径不在读/执行允许目录内。")

    def test_denies_write_outside_working_dir(self) -> None:
        decision = self.permissions.evaluate_write_path("/Users/example/Desktop/file.txt")

        self.assertEqual(decision.action, "deny")
        self.assertIsNotNone(decision.request)
        self.assertEqual(decision.request.reason, "目标路径不在写入允许目录内。")

    def test_allows_writing_system_temp_dir(self) -> None:
        decision = self.permissions.evaluate_write_path("/tmp/opendog-scratch/file.txt")

        self.assertEqual(decision.action, "allow")

    def test_allows_shell_paths_inside_system_temp_dir(self) -> None:
        decision = self.permissions.evaluate_shell("mkdir -p /tmp/opendog-scratch")

        self.assertEqual(decision.action, "allow")

    def test_allows_reading_skill_roots(self) -> None:
        decision = self.permissions.evaluate_read_path(
            "/Users/example/opendog-engine/workspace/skills/docx/SKILL.md"
        )

        self.assertEqual(decision.action, "allow")

    def test_denies_writing_skill_roots(self) -> None:
        decision = self.permissions.evaluate_write_path(
            "/Users/example/opendog-engine/workspace/skills/docx/SKILL.md"
        )

        self.assertEqual(decision.action, "deny")


if __name__ == "__main__":
    unittest.main()

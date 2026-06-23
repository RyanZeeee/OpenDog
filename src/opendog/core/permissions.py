from __future__ import annotations

import os
import re
import shlex
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

PermissionAction = Literal["allow", "deny"]
PermissionScope = Literal["allow", "deny"]
PermissionOperation = Literal["read_path", "write_path", "run_shell"]


@dataclass
class PermissionRequest:
    tool_name: str
    operation: PermissionOperation
    target: str
    working_dir: Path
    reason: str
    command: Optional[str] = None


@dataclass
class PermissionDecision:
    action: PermissionAction
    reason: str = ""
    request: Optional[PermissionRequest] = None

@dataclass
class PermissionManager:
    working_dir: Path
    workspace_root: Path
    skill_roots: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.working_dir = self.working_dir.resolve(strict=False)
        self.workspace_root = self.workspace_root.resolve(strict=False)
        self.skill_roots = [
            root.resolve(strict=False) for root in self.skill_roots
        ]

    def resolve_user_path(self, path: str) -> Path:
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = self.working_dir / resolved
        return resolved.resolve(strict=False)

    def evaluate_read_path(self, path: str, tool_name: str = "read") -> PermissionDecision:
        resolved = self.resolve_user_path(path)
        if self.is_read_execute_allowed(resolved):
            return PermissionDecision("allow")

        return PermissionDecision(
            "deny",
            "目标路径不在读/执行允许目录内。",
            request=self._make_request(
                tool_name=tool_name,
                operation="read_path",
                target=resolved,
                reason="目标路径不在读/执行允许目录内。",
            ),
        )

    def evaluate_write_path(self, path: str, tool_name: str = "write") -> PermissionDecision:
        resolved = self.resolve_user_path(path)
        if self.is_write_allowed(resolved):
            return PermissionDecision("allow")

        return PermissionDecision(
            "deny",
            "目标路径不在写入允许目录内。",
            request=self._make_request(
                tool_name=tool_name,
                operation="write_path",
                target=resolved,
                reason="目标路径不在写入允许目录内。",
            ),
        )

    def evaluate_shell(self, command: str) -> PermissionDecision:
        command_for_scan = self.strip_heredoc_bodies(command)
        segments = self.shell_command_segments(command_for_scan)
        if len(segments) > 1:
            for segment in segments:
                decision = self.evaluate_shell(segment)
                if decision.action != "allow":
                    return decision
            return PermissionDecision("allow")

        try:
            tokens = shlex.split(command_for_scan)
        except ValueError:
            return PermissionDecision("allow")

        if not tokens:
            return PermissionDecision("allow")

        if self._uses_command_substitution(command_for_scan):
            return PermissionDecision("allow")

        executable = Path(tokens[0]).name
        if executable == "osascript":
            return PermissionDecision(
                "deny",
                "osascript 可能通过系统应用操作允许目录外的资源。",
                request=self._make_request(
                    tool_name="bash",
                    operation="run_shell",
                    target=Path("/System/Library/CoreServices"),
                    reason="osascript 可能通过系统应用操作允许目录外的资源。",
                    command=command,
                ),
            )

        outside_targets = self.shell_outside_targets(command_for_scan, tokens)
        if outside_targets:
            target = self._common_target(outside_targets)
            return PermissionDecision(
                "deny",
                "命令访问了允许目录外的路径。",
                request=self._make_request(
                    tool_name="bash",
                    operation="run_shell",
                    target=target,
                    reason="命令访问了允许目录外的路径。",
                    command=command,
                ),
            )

        return PermissionDecision("allow")

    def shell_command_segments(self, command: str) -> list[str]:
        segments: list[str] = []
        current: list[str] = []
        in_single_quote = False
        in_double_quote = False
        escaped = False
        index = 0

        while index < len(command):
            char = command[index]

            if escaped:
                current.append(char)
                escaped = False
                index += 1
                continue

            if char == "\\":
                current.append(char)
                escaped = True
                index += 1
                continue

            if char == "'" and not in_double_quote:
                in_single_quote = not in_single_quote
                current.append(char)
                index += 1
                continue

            if char == '"' and not in_single_quote:
                in_double_quote = not in_double_quote
                current.append(char)
                index += 1
                continue

            if not in_single_quote and not in_double_quote:
                if char in {";", "\n"}:
                    self._append_shell_segment(segments, current)
                    current = []
                    index += 1
                    continue

                two_chars = command[index : index + 2]
                if two_chars in {"&&", "||"}:
                    self._append_shell_segment(segments, current)
                    current = []
                    index += 2
                    continue

            current.append(char)
            index += 1

        self._append_shell_segment(segments, current)
        return segments

    def _append_shell_segment(self, segments: list[str], current: list[str]) -> None:
        segment = "".join(current).strip()
        if segment:
            segments.append(segment)

    def shell_outside_targets(self, command: str, tokens: list[str]) -> list[Path]:
        targets: list[Path] = []

        for index, token in enumerate(tokens):
            if self._looks_like_parent_traversal(token):
                targets.append((self.working_dir / token).resolve(strict=False))
                continue

            if token.startswith("~"):
                targets.append(Path(token).expanduser().resolve(strict=False))
                continue

            token_path = self._absolute_token_path(token)
            if token_path is not None:
                if index == 0:
                    continue
                targets.append(token_path)
                continue

            for match in self.absolute_path_pattern.finditer(token):
                raw_path = match.group(0)
                if index == 0 and token == raw_path:
                    continue
                targets.append(Path(raw_path).resolve(strict=False))

        for match in self.env_path_pattern.finditer(command):
            expanded = os.path.expandvars(match.group(0))
            if "$" not in expanded:
                targets.append(Path(expanded).expanduser().resolve(strict=False))

        return [
            target
            for target in self._dedupe_paths(targets)
            if not self.is_read_execute_allowed(target) and not self.is_write_allowed(target)
        ]

    def strip_heredoc_bodies(self, command: str) -> str:
        lines = command.splitlines()
        result: list[str] = []
        index = 0

        while index < len(lines):
            line = lines[index]
            result.append(line)
            delimiters = self.heredoc_delimiters(line)
            index += 1

            for delimiter in delimiters:
                while index < len(lines):
                    if lines[index].strip() == delimiter:
                        result.append(lines[index])
                        index += 1
                        break
                    index += 1

        return "\n".join(result)

    def heredoc_delimiters(self, line: str) -> list[str]:
        delimiters: list[str] = []
        pattern = re.compile(r"<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|([A-Za-z_][A-Za-z0-9_]*))")
        for match in pattern.finditer(line):
            delimiter = next(group for group in match.groups() if group)
            delimiters.append(delimiter)
        return delimiters

    def clear_turn_grants(self) -> None:
        return None

    def _make_request(
        self,
        tool_name: str,
        operation: PermissionOperation,
        target: Path,
        reason: str,
        command: Optional[str] = None,
    ) -> PermissionRequest:
        return PermissionRequest(
            tool_name=tool_name,
            operation=operation,
            target=str(target.resolve(strict=False)),
            working_dir=self.working_dir,
            reason=reason,
            command=command,
        )

    def is_read_execute_allowed(self, path: Path) -> bool:
        return any(self._is_under(path, root) for root in self.read_execute_roots)

    def is_write_allowed(self, path: Path) -> bool:
        return any(self._is_under(path, root) for root in self.write_roots)

    def shell_environment(self, include_user_home: bool = False) -> dict[str, str]:
        tmp_dir = self.working_dir / ".opendog_tmp"
        home_dir = tmp_dir / "home"
        npm_project_dir = tmp_dir / "npm-project"
        npm_project_bin_dir = npm_project_dir / "node_modules" / ".bin"
        npm_project_modules_dir = npm_project_dir / "node_modules"
        python_cache_dir = tmp_dir / "python"
        node_cache_dir = tmp_dir / "node"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        home_dir.mkdir(parents=True, exist_ok=True)
        npm_project_dir.mkdir(parents=True, exist_ok=True)
        python_cache_dir.mkdir(parents=True, exist_ok=True)
        node_cache_dir.mkdir(parents=True, exist_ok=True)
        skill_dirs = self.skill_dirs()
        skill_node_modules = self.skill_node_modules_roots()
        skill_python_paths = self.skill_python_paths(skill_dirs)
        path_parts = [
            str(npm_project_bin_dir),
            *[
                str(node_modules / ".bin")
                for node_modules in skill_node_modules
                if (node_modules / ".bin").exists()
            ],
            os.environ.get(
                "PATH",
                "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            ),
        ]
        env = os.environ.copy() if include_user_home else {}
        env.update(
            {
                "HOME": os.environ.get("HOME", str(home_dir)) if include_user_home else str(home_dir),
                "PWD": str(self.working_dir),
                "TMPDIR": str(tmp_dir),
                "TMP": str(tmp_dir),
                "TEMP": str(tmp_dir),
                "PATH": os.pathsep.join(path_parts),
                "NODE_COMPILE_CACHE": str(node_cache_dir),
                "PYTHONPYCACHEPREFIX": str(python_cache_dir),
            }
        )
        node_path_roots = [npm_project_modules_dir, *skill_node_modules]
        if node_path_roots:
            existing_node_path = env.get("NODE_PATH", "")
            node_path_parts = [str(path) for path in node_path_roots]
            if existing_node_path:
                node_path_parts.append(existing_node_path)
            env["NODE_PATH"] = os.pathsep.join(node_path_parts)
        if skill_python_paths:
            existing_python_path = env.get("PYTHONPATH", "")
            python_path_parts = [str(path) for path in skill_python_paths]
            if existing_python_path:
                python_path_parts.append(existing_python_path)
            env["PYTHONPATH"] = os.pathsep.join(python_path_parts)
        return env

    def skill_dirs(self) -> list[Path]:
        roots: list[Path] = []
        for skill_root in self.skill_roots:
            if (skill_root / "SKILL.md").exists():
                roots.append(skill_root.resolve(strict=False))
                continue

            for skill_file in skill_root.glob("*/SKILL.md"):
                roots.append(skill_file.parent.resolve(strict=False))

        return self._dedupe_paths(roots)

    def skill_node_modules_roots(self) -> list[Path]:
        roots: list[Path] = []
        for skill_dir in self.skill_dirs():
            node_modules = skill_dir / "node_modules"
            if node_modules.exists():
                roots.append(node_modules.resolve(strict=False))

        return self._dedupe_paths(roots)

    def skill_python_paths(self, skill_dirs: list[Path]) -> list[Path]:
        paths: list[Path] = []
        for skill_dir in skill_dirs:
            paths.append(skill_dir)
            scripts_dir = skill_dir / "scripts"
            if scripts_dir.exists():
                paths.append(scripts_dir)

        return self._dedupe_paths(paths)

    @property
    def read_execute_roots(self) -> list[Path]:
        return self._dedupe_paths(
            [
                self.working_dir,
                *self.system_temp_roots,
                *self.skill_roots,
            ]
        )

    @property
    def write_roots(self) -> list[Path]:
        return self._dedupe_paths([self.working_dir, *self.system_temp_roots])

    @property
    def system_temp_roots(self) -> list[Path]:
        return self._dedupe_paths(
            [
                Path(tempfile.gettempdir()),
                Path("/tmp"),
                Path("/private/tmp"),
                Path("/var/tmp"),
            ]
        )

    @property
    def absolute_path_pattern(self) -> re.Pattern[str]:
        return re.compile(
            r"/(?:Users|Volumes|private|etc|var|tmp|System|Library|Applications|opt|bin|usr|sbin)(?:/[^\s'\";)]*)?"
        )

    @property
    def env_path_pattern(self) -> re.Pattern[str]:
        return re.compile(
            r"(?:\$HOME|\$PWD|\$TMPDIR|\$TMP|\$TEMP|\$\{HOME\}|\$\{PWD\}|\$\{TMPDIR\}|\$\{TMP\}|\$\{TEMP\})(?:/[^\s'\";)]*)?"
        )

    def _looks_like_parent_traversal(self, token: str) -> bool:
        return token in {"..", "../"} or token.startswith("../") or "/../" in token

    def _uses_command_substitution(self, command: str) -> bool:
        return "`" in command or "$(" in command

    def _absolute_token_path(self, token: str) -> Optional[Path]:
        candidates = [token]
        if "=" in token:
            candidates.append(token.split("=", 1)[1])

        for candidate in candidates:
            if candidate.startswith("/"):
                return Path(candidate).expanduser().resolve(strict=False)

        return None

    def _common_target(self, targets: list[Path]) -> Path:
        if not targets:
            return self.working_dir
        return targets[0]

    def _dedupe_paths(self, paths: list[Path]) -> list[Path]:
        deduped: list[Path] = []
        for path in paths:
            resolved = path.resolve(strict=False)
            if resolved not in deduped:
                deduped.append(resolved)
        return deduped

    def _is_under(self, path: Path, root: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
            return True
        except ValueError:
            return False

    def _format_roots(self, roots: list[Path]) -> str:
        return ", ".join(str(root) for root in roots)


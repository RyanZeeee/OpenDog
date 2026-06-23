from __future__ import annotations

import asyncio
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable, Optional

from opendog.core.agent_loader import AgentDef
from opendog.core.permissions import PermissionDecision, PermissionManager, PermissionRequest, PermissionScope
from opendog.core.session_state import SessionState
from opendog.core.skill_registry import SkillDef, SkillRegistry
from opendog.provider.llm.base import LLMProvider, LLMToolCall
from opendog.tools import ToolRegistry
from opendog.utils.config import HistoryConfig


@dataclass
class Agent:
    agent_def: AgentDef
    llm: LLMProvider
    skills_dir: Path
    workspace_root: Path
    working_dir: Path
    tools: ToolRegistry
    history: HistoryConfig
    command_registry: "CommandRegistry | None" = field(default=None, init=False)

    def create_session(
        self,
        session_id: Optional[str] = None,
        session_store: object = None,
        resume: bool = False,
    ) -> "AgentSession":
        from opendog.cli.commands import CommandRegistry
        from opendog.core.session_store import SessionStore

        store: SessionStore | None = session_store  # type: ignore[assignment]
        session_id = session_id or str(uuid.uuid4())
        state = SessionState(
            system_prompt=self.agent_def.system_prompt,
            session_id=session_id,
            max_history_tokens=self.history.max_tokens,
            keep_recent_messages=self.history.keep_recent_messages,
            summary_max_tokens=self.history.summary_max_tokens,
            store=store,
            agent_name=self.agent_def.name,
        )
        if resume and store:
            messages = store.load_messages(session_id)
            state.load_messages(messages)
        elif store:
            store.upsert_index(state._make_index_entry())
        if not hasattr(self, "command_registry") or self.command_registry is None:
            self.command_registry = CommandRegistry.with_builtins(self.skills_dir)
        return AgentSession(
            agent=self,
            state=state,
            skills=SkillRegistry.load(
                self.skills_dir,
                allowed_names=self.agent_def.allowed_skills,
            ),
            tools=self.tools,
            command_registry=self.command_registry,
        )


OVERFLOW_MESSAGE = "Context limit exceeded. Please run /compact, then retry this message."


@dataclass
class AgentSession:
    agent: Agent
    state: SessionState
    skills: SkillRegistry
    tools: ToolRegistry
    command_registry: "CommandRegistry | None" = field(default=None)
    current_agent_def: AgentDef = field(init=False)
    permission_handler: Optional[
        Callable[[PermissionRequest], Awaitable[PermissionScope]]
    ] = None
    active_skill: Optional[SkillDef] = None
    turn_file_write_attempted: bool = False
    turn_successful_writes: list[Path] = field(default_factory=list)
    pending_guidance: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.current_agent_def = self.agent.agent_def
        self.permissions = PermissionManager(
            working_dir=self.agent.working_dir,
            workspace_root=self.agent.workspace_root,
            skill_roots=[self.agent.skills_dir],
        )

    @property
    def session_id(self) -> str:
        return self.state.session_id

    def build_system_prompt(self) -> str:
        runtime_section = (
            "## Runtime Paths\n\n"
            f"- Working directory: {self.agent.working_dir}\n"
            f"- opendog workspace configuration directory: {self.agent.workspace_root}\n\n"
            "File tools and shell commands run in the working directory by default.\n"
            "The workspace is only the source of opendog configuration. "
            "For MCP management, use mcp_list_servers, mcp_start_server, and mcp_stop_server."
        )
        tool_discipline_section = (
            "## Tool Use Discipline\n\n"
            "### File Writing\n"
            "Use write to create or overwrite files. If the content is too large and the write fails, split it into chunks: "
            "use write for the first chunk and append for later chunks. Do not switch to bash, Python, or base64 for file writing.\n\n"
            "### File Editing\n"
            "Use edit for one replacement in a file, and multiedit for multiple replacements in the same file.\n\n"
            "### Verification After Writing\n"
            "After writing a long file, you must call tools to check completeness and obvious errors: missing sections, incorrect order, "
            "unclosed syntax structures, or accidental code/markup that should not be displayed.\n\n"
            "### Output Directory\n"
            "Final artifacts requested by the user must be written to the working directory unless the user explicitly specifies another path. "
            ".opendog_tmp is only for temporary scripts, temporary dependencies, and caches, not final artifacts. "
            "When temporary scripts generate final artifacts, pass an absolute output path inside the working directory or provide the output path as a command argument. "
            "Do not infer final artifact locations with ../ or ../../ inside scripts.\n\n"
            "### Path Clarity\n"
            "All tool arguments and shell command paths must be clear and resolvable. "
            "Prefer paths relative to the working directory. When an absolute path is required, write the complete absolute path directly. "
            "If a path contains spaces, wrap the full path in double quotes; do not use backslash-escaped spaces. "
            "Do not use $HOME, ${HOME}, ~, $PWD, or ${PWD} for important paths, and do not split one path into multiple concatenated parts. "
            "Unclear paths will be rejected by the safety boundary.\n\n"
            "### Operations Outside The Project\n"
            "Do not proactively access paths outside the working directory unless the user explicitly asks you to read, modify, or delete a specific external location. "
            "If an external operation is truly necessary, first ensure the user's instruction clearly names that location or intent, then call the tool so the permission request can be shown. "
            "If the user rejects the external operation or it times out as denied, do not try another path, another command, or repeated requests. "
            "Stop that operation, explain that it was denied, and confirm whether the user really wants to continue with the external location.\n\n"
            "### Dependency Installation\n"
            "Do not install code dependencies globally. Prefer installing npm dependencies into .opendog_tmp. "
            "If a skill example installs dependencies globally, do not copy that pattern; create a local temporary project instead, and do not switch to /tmp. "
            "Prefer domestic mirrors when installing code dependencies. If a mirror is unavailable or the package does not exist, switch mirrors or fall back to the official source. "
            "If similar installation commands time out or fail, do not retry blindly more than twice; change the source based on the error or clearly explain the failure.\n\n"
            "### Content Accuracy\n"
            "Omitted content in history summaries is not the full original text. When file details are needed, read the real file again with the read tool.\n\n"
            "### Bash Boundary\n"
            "Use bash only for running, building, converting, and verifying. Do not use bash to write large files."
        )
        skill_section = self.skills.build_prompt_section()
        sections = [
            self.current_agent_def.system_prompt,
            runtime_section,
            tool_discipline_section,
        ]
        active_skill_section = self.build_active_skill_section()
        if active_skill_section:
            sections.append(active_skill_section)
        if skill_section:
            sections.append(skill_section)
        return "\n\n".join(sections)

    def switch_agent(self, agent_def: AgentDef) -> None:
        self.current_agent_def = agent_def
        self.state.agent_name = agent_def.name
        self.skills = SkillRegistry.load(
            self.agent.skills_dir,
            allowed_names=agent_def.allowed_skills,
        )
        self.active_skill = None
        self.state.set_system_prompt(self.build_system_prompt())
        if self.state.store:
            self.state.store.upsert_index(self.state._make_index_entry())

    def build_active_skill_section(self) -> str:
        if self.active_skill is None:
            return ""
        return (
            "## Active Skill\n\n"
            f"Loaded skill: {self.active_skill.name}\n"
            f"SKILL.md: {self.active_skill.path}\n\n"
            "Resolve all relative paths mentioned in SKILL.md relative to the directory containing that SKILL.md. "
            "Do not rewrite them as scripts paths under the workspace root.\n"
            "Continue following the SKILL.md you just read. Prefer tools and files provided by the skill. "
            "If required system tools or dependencies are missing, install them immediately into the project's local .opendog_tmp directory. "
            "After installation, execute the method and tools specified by SKILL.md locally in the project.\n"
        )

    def activate_skill_from_path(self, path: Path) -> None:
        skill = self.skills.find_by_skill_file(path)
        if skill is not None:
            self.active_skill = skill

    def add_guidance(self, text: str) -> None:
        text = text.strip()
        if text:
            self.pending_guidance.append(text)

    def has_pending_guidance(self) -> bool:
        return bool(self.pending_guidance)

    def consume_guidance_into_history(self) -> int:
        if not self.pending_guidance:
            return 0

        guidance_items = self.pending_guidance[:]
        self.pending_guidance.clear()
        if len(guidance_items) == 1:
            content = (
                "[Current Task Guidance]\n"
                "The user added the following guidance while the current task was running. Apply it to the current task:\n"
                f"{guidance_items[0]}"
            )
        else:
            joined = "\n".join(f"- {item}" for item in guidance_items)
            content = (
                "[Current Task Guidance]\n"
                "The user added the following guidance while the current task was running. Apply the items in order:\n"
                f"{joined}"
            )
        self.state.add_message({"role": "user", "content": content})
        return len(guidance_items)

    async def chat(self, message: str) -> str:
        status = self.state.compact_if_needed()
        if status == "overflow":
            return OVERFLOW_MESSAGE
        self.permissions.clear_turn_grants()
        self.active_skill = None
        self.turn_file_write_attempted = False
        self.turn_successful_writes.clear()
        self.state.add_message({"role": "user", "content": message})

        while True:
            self.consume_guidance_into_history()
            self.state.set_system_prompt(self.build_system_prompt())
            try:
                llm_response = await self.agent.llm.chat_completion(
                    messages=self.state.build_messages(),
                    tools=self.tools.get_tool_schemas(),
                    tool_choice="auto",
                )
            except Exception as exc:
                if self._is_context_overflow_error(exc):
                    return OVERFLOW_MESSAGE
                raise

            assistant_message = {
                "role": "assistant",
                "content": llm_response.content,
            }
            if llm_response.tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.name,
                            "arguments": tool_call.arguments,
                        },
                    }
                    for tool_call in llm_response.tool_calls
                ]
            self.state.add_message(assistant_message)

            if llm_response.tool_calls:
                await self.handle_tool_calls(llm_response.tool_calls)
                continue

            if self.has_pending_guidance():
                continue

            if llm_response.stop_reason == "content_filter":
                return llm_response.content or "Sorry, I cannot answer this request."

            return llm_response.content

    async def stream_chat(self, message: str) -> AsyncIterator[dict]:
        status = self.state.compact_if_needed()
        if status == "overflow":
            yield {"type": "text", "content": OVERFLOW_MESSAGE}
            return
        self.permissions.clear_turn_grants()
        turn_start = len(self.state.messages)
        active_skill_start = self.active_skill
        file_write_attempted_start = self.turn_file_write_attempted
        successful_writes_start = list(self.turn_successful_writes)
        pending_guidance_start = list(self.pending_guidance)
        self.active_skill = None
        self.turn_file_write_attempted = False
        self.turn_successful_writes.clear()
        self.state.add_message({"role": "user", "content": message})

        try:
            while True:
                guidance_count = self.consume_guidance_into_history()
                if guidance_count:
                    yield {"type": "status", "content": "正在处理引导内容"}

                self.state.set_system_prompt(self.build_system_prompt())
                content_parts: list[str] = []
                tool_builders: dict[int, dict[str, str]] = {}
                stop_reason: Optional[str] = None

                try:
                    async for chunk in self.agent.llm.stream_chat_completion(
                        messages=self.state.build_messages(),
                        tools=self.tools.get_tool_schemas(),
                        tool_choice="auto",
                    ):
                        if chunk.content:
                            content_parts.append(chunk.content)
                            yield {"type": "text", "content": chunk.content}

                        if chunk.tool_call_index is not None:
                            builder = tool_builders.setdefault(
                                chunk.tool_call_index,
                                {"id": "", "name": "", "arguments": ""},
                            )
                            if chunk.tool_call_id:
                                builder["id"] = chunk.tool_call_id
                            if chunk.tool_call_name:
                                builder["name"] += chunk.tool_call_name
                            if chunk.tool_call_arguments:
                                builder["arguments"] += chunk.tool_call_arguments

                        if chunk.stop_reason:
                            stop_reason = chunk.stop_reason

                except Exception as exc:
                    if self._is_context_overflow_error(exc):
                        yield {"type": "text", "content": OVERFLOW_MESSAGE}
                        return
                    raise

                content = "".join(content_parts)
                tool_calls = self.build_stream_tool_calls(tool_builders)
                assistant_message = self.build_assistant_message(content, tool_calls)
                self.state.add_message(assistant_message)

                if tool_calls:
                    names = ', '.join(tc.name for tc in tool_calls)
                    yield {
                        "type": "status",
                        "content": f"调用工具：{names}",
                    }
                    await self.handle_tool_calls_stream(tool_calls)
                    yield {"type": "status", "content": f"工具调用中（{names}）"}
                    continue

                if self.has_pending_guidance():
                    continue

                if stop_reason == "content_filter":
                    if not content:
                        yield {"type": "text", "content": "Sorry, I cannot answer this request."}
                    return

                return
        except asyncio.CancelledError:
            del self.state.messages[turn_start:]
            self.active_skill = active_skill_start
            self.turn_file_write_attempted = file_write_attempted_start
            self.turn_successful_writes = successful_writes_start
            self.pending_guidance = pending_guidance_start
            raise

    def build_stream_tool_calls(
        self,
        tool_builders: dict[int, dict[str, str]],
    ) -> list[LLMToolCall]:
        tool_calls = []
        for index in sorted(tool_builders):
            item = tool_builders[index]
            if not item["name"]:
                continue
            tool_calls.append(
                LLMToolCall(
                    id=item["id"] or f"tool_call_{index}",
                    name=item["name"],
                    arguments=item["arguments"] or "{}",
                )
            )
        return tool_calls

    @staticmethod
    def _is_context_overflow_error(exc: Exception) -> bool:
        name = type(exc).__name__.lower()
        msg = str(exc).lower()
        combined = f"{name} {msg}"
        return any(
            kw in combined
            for kw in ("context", "token limit", "max token", "maximum length", "exceeded")
        )

    def build_assistant_message(
        self,
        content: str,
        tool_calls: list[LLMToolCall],
    ) -> dict:
        assistant_message = {
            "role": "assistant",
            "content": content,
        }
        if tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.name,
                        "arguments": tool_call.arguments,
                    },
                }
                for tool_call in tool_calls
            ]
        return assistant_message

    async def handle_tool_calls_stream(self, tool_calls: list[LLMToolCall]) -> None:
        await self.handle_tool_calls(tool_calls)

    async def handle_tool_calls(self, tool_calls: list) -> None:
        for tool_call in tool_calls:
            tool_result = await self.execute_tool_call(tool_call)
            self.state.add_message(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                }
            )

    async def execute_tool_call(self, tool_call) -> str:
        if tool_call.name in ("write", "append"):
            self.turn_file_write_attempted = True

        try:
            arguments = json.loads(tool_call.arguments or "{}")
        except json.JSONDecodeError as exc:
            if tool_call.name in ("write", "append"):
                return self.dumps_tool_result(
                    {
                        "ok": False,
                        "error": f"Invalid tool arguments JSON: {exc}",
                        "reason": (
                            "The file content was probably too large or had complex escaping "
                            "for one tool call."
                        ),
                        "next_action": (
                            "Do not switch to bash/Python/base64. Retry with a smaller chunk: "
                            "use write for the first chunk and append for following chunks."
                        ),
                    }
                )
            return self.dumps_tool_result(
                {
                    "ok": False,
                    "error": f"Invalid tool arguments JSON: {exc}",
                    "arguments": tool_call.arguments,
                }
            )

        guarded_result = self.guard_redundant_write_strategy(tool_call.name, arguments)
        if guarded_result is not None:
            return guarded_result

        try:
            result = await self.tools.execute_tool(
                tool_call.name,
                session=self,
                **arguments,
            )
            MAX_TOOL_RESULT_CHARS = 200_000
            if len(result) > MAX_TOOL_RESULT_CHARS:
                result = (
                    result[:MAX_TOOL_RESULT_CHARS]
                    + f"\n\n[Result truncated. Original result length: {len(result)} characters "
                    + f"(single tool result limit: {MAX_TOOL_RESULT_CHARS} characters). "
                    + "Use the read tool with the offset parameter to read the full content in chunks if needed.]"
                )
            return result
        except Exception as exc:
            return self.dumps_tool_result(
                {
                    "ok": False,
                    "error": f"Error executing tool {tool_call.name}: {exc}",
                }
            )

    def dumps_tool_result(self, result: object) -> str:
        return json.dumps(result, ensure_ascii=False)

    def record_successful_write(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved not in self.turn_successful_writes:
            self.turn_successful_writes.append(resolved)

    def guard_redundant_write_strategy(
        self,
        tool_name: str,
        arguments: dict,
    ) -> Optional[str]:
        if tool_name != "bash" or not self.turn_file_write_attempted:
            return None

        command = str(arguments.get("command", ""))
        if not command or not self.is_shell_file_write_command(command):
            return None

        return self.dumps_tool_result(
            {
                "ok": True,
                "skipped": True,
                "reason": (
                    "This user turn already started file writing with write/append. "
                    "Do not switch to bash/Python/base64/heredoc for file writing."
                ),
                "written_files": [str(path) for path in self.turn_successful_writes],
                "next_action": (
                    "If no chunk has succeeded yet, retry write with a smaller first chunk. "
                    "If the file still needs more content, use append. Otherwise run only a "
                    "non-writing verification command, or answer the user with the created file path."
                ),
                "skipped_command": command,
            }
        )

    def is_shell_file_write_command(self, command: str) -> bool:
        if "<<" in command:
            return True

        write_patterns = [
            r"(^|[;&|]\s*)cat\b[^;&|]*>>?\s*['\"]?[^&\s]",
            r"\btee\b(?:\s+-a)?\s+['\"]?[^&\s]",
            r"(?<!\d)>>?\s*['\"]?[^&\s]",
            r"\bpython3?\b[\s\S]*(?:open\(|write_text\(|Path\()[\s\S]*(?:[\"']w[\"']|write_text\()",
            r"\bnode\b[\s\S]*(?:writeFileSync|writeFile)\s*\(",
        ]
        return any(re.search(pattern, command) for pattern in write_patterns)

    async def _resolve_path(
        self,
        path: str,
        tool_name: str,
        evaluate: Callable[[str, str], PermissionDecision],
    ) -> Path:
        decision = evaluate(path, tool_name=tool_name)
        if decision.action == "allow":
            return self.permissions.resolve_user_path(path)
        if decision.request is not None and await self.request_permission(decision.request) == "allow":
            return Path(decision.request.target)
        raise ValueError(self.permission_denied_message())

    async def resolve_read_path(self, path: str, tool_name: str = "read") -> Path:
        return await self._resolve_path(path, tool_name, self.permissions.evaluate_read_path)

    async def resolve_write_path(self, path: str, tool_name: str = "write") -> Path:
        return await self._resolve_path(path, tool_name, self.permissions.evaluate_write_path)

    async def approve_shell_command(self, command: str) -> tuple[bool, str, list[Path], bool]:
        decision = self.permissions.evaluate_shell(command)
        if decision.action == "allow":
            include_user_home = "$HOME" in command or "${HOME}" in command or "~" in command
            return True, "", [], include_user_home
        if decision.request is not None and await self.request_permission(decision.request) == "allow":
            include_user_home = "$HOME" in command or "${HOME}" in command or "~" in command
            target = Path(decision.request.target)
            root = target if target.is_dir() else target.parent
            return True, "", [root], include_user_home
        return False, self.permission_denied_message(), [], False

    def permission_denied_message(self) -> str:
        return (
            "The user denied this operation: the path is outside the project boundary, "
            "or the instruction contains an unclear path. The safety boundary rejected this tool call. "
            "Do not try another path, another command, or repeated requests. "
            "First confirm the exact path and intended operation with the user."
        )

    async def request_permission(self, request: PermissionRequest) -> PermissionScope:
        if self.permission_handler is None:
            return "deny"
        return await self.permission_handler(request)

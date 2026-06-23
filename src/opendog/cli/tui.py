from __future__ import annotations

import asyncio
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from typing import Optional

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import ConditionalContainer, HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style

from opendog.cli.startup import PIXEL_LOGO, StartupStatus, collect_startup_status
from opendog.core.agent import Agent, AgentSession
from opendog.core.conversation_runtime import ConversationRuntime
from opendog.core.permissions import PermissionRequest, PermissionScope

CHAT_WIDTH = 68
LOGO_WIDTH = len(PIXEL_LOGO[0]) * 2
STARTUP_HEIGHT = len(PIXEL_LOGO) + 2
HEADER_DIVIDER = " │ "
HEADER_INNER_WIDTH = CHAT_WIDTH - 4
HEADER_INFO_WIDTH = HEADER_INNER_WIDTH - LOGO_WIDTH - len(HEADER_DIVIDER)
PERMISSION_TIMEOUT_SECONDS = 30
USER_INPUT_COLOR = "#FF6801"
SPINNER_FRAMES = [
    "\u280b", "\u2819", "\u2839", "\u2838", "\u283c",
    "\u2834", "\u2826", "\u2827", "\u2807", "\u280f",
]


class ScrollableWindow(Window):
    """Window 子类，接管 vertical_scroll 实现鼠标/触控板滚动与自动跟随。

    父类 _scroll 会在每次渲染时根据 cursor_position 重置
    vertical_scroll（因为 cursor 默认在 (0,0)，导致 scroll 被强制归零）。
    这里覆盖 _scroll 只做边界钳位，不追踪光标位置。
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shared_scroll = 0
        self.user_scrolled_away = False

    @property
    def vertical_scroll(self) -> int:
        return self.shared_scroll

    @vertical_scroll.setter
    def vertical_scroll(self, value: int) -> None:
        self.shared_scroll = max(0, value)

    def _scroll(self, ui_content, width: int, height: int) -> None:
        """只做边界钳位，禁止父类根据 cursor_position=0 强制滚回顶部。"""
        if ui_content.line_count == 0:
            self.shared_scroll = 0
            return
        if not self.allow_scroll_beyond_bottom():
            max_scroll = max(0, ui_content.line_count - height)
            if self.shared_scroll > max_scroll:
                self.shared_scroll = max_scroll
        self.shared_scroll = max(0, self.shared_scroll)

    def _scroll_up(self) -> None:
        info = self.render_info
        if info is None:
            return
        if info.vertical_scroll > 0:
            self.shared_scroll = info.vertical_scroll - 1
            self.user_scrolled_away = True

    def _scroll_down(self) -> None:
        info = self.render_info
        if info is None:
            return
        max_scroll = max(0, info.content_height - info.window_height)
        if info.vertical_scroll < max_scroll:
            self.shared_scroll = info.vertical_scroll + 1
        # 滚到底部就清除标记，恢复自动跟随
        if info.vertical_scroll + 1 >= max_scroll:
            self.user_scrolled_away = False


@dataclass
class ChatMessage:
    role: str
    content: str


class TuiChatLoop:
    def __init__(self, context: object, agent: Agent, session: AgentSession) -> None:
        self.context = context
        self.agent = agent
        self.session = session
        self.status = collect_startup_status(context, agent, session)

        self._mcp_manager = getattr(session.tools, '_mcp_manager', None)
        if self._mcp_manager is not None:
            self._mcp_manager.start_enabled_servers_background()
        self.runtime = ConversationRuntime(
            context=context,
            agent=agent,
            session=session,
            mcp_manager=self._mcp_manager,
        )

        self.messages: list[ChatMessage] = self._restore_messages(session)
        self.status_line = (
            '输入提示词继续对话 · 输入\u201c退出\u201d结束'
            if self.messages
            else '输入提示词开始对话 · 输入\u201c退出\u201d结束'
        )
        self.current_answer = ""
        self._waiting = False
        self.guidance_queue: list[str] = []
        self.generating_task: Optional[asyncio.Task] = None
        self.permission_request: Optional[PermissionRequest] = None
        self.permission_future: Optional[asyncio.Future] = None
        self.permission_deadline: Optional[float] = None

        self.output_window = ScrollableWindow(
            content=None,
            height=Dimension(weight=1, min=3),
            allow_scroll_beyond_bottom=False,
            wrap_lines=False,
            always_hide_cursor=True,
        )
        self.output_control = FormattedTextControl(self.render_output)
        self.output_window.content = self.output_control

        self.input_buffer = Buffer(multiline=False)
        self.output_control = FormattedTextControl(self.render_output)
        self.status_control = FormattedTextControl(self.render_status)
        self.permission_control = FormattedTextControl(self.render_permission)
        self.app = self.build_application()
        self.session.permission_handler = self.request_permission

    def _restore_messages(self, session: AgentSession) -> list[ChatMessage]:
        """从 session 历史消息恢复对话显示列表。"""
        result: list[ChatMessage] = []
        for msg in session.state.messages:
            role = msg.get("role", "")
            if role == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    result.append(ChatMessage("user", content))
            elif role == "assistant":
                content = msg.get("content", "")
                # 跳过纯摘要消息（压缩产物，不显示在界面上）
                is_summary = isinstance(content, str) and (
                    content.startswith("[opendog History Summary]")
                    or content.startswith("[opendog 历史摘要]")
                )
                if isinstance(content, str) and content and not is_summary:
                    result.append(ChatMessage("assistant", content))
            # tool 消息不直接显示
        return result

    def build_application(self) -> Application:
        permission_open = Condition(lambda: self.permission_request is not None)
        root = HSplit(
            [
                self.output_window,
                ConditionalContainer(
                    Window(
                        self.permission_control,
                        height=8,
                        wrap_lines=False,
                        always_hide_cursor=True,
                    ),
                    filter=permission_open,
                ),
                Window(
                    self.status_control,
                    height=1,
                    wrap_lines=False,
                    always_hide_cursor=True,
                ),
                VSplit(
                    [
                        Window(
                            FormattedTextControl([("class:prompt", ">: ")]),
                            width=3,
                            wrap_lines=False,
                        ),
                        Window(
                            BufferControl(buffer=self.input_buffer),
                            height=4,
                            wrap_lines=False,
                        ),
                    ],
                    height=4,
                ),
            ]
        )

        bindings = KeyBindings()

        @bindings.add("enter", eager=True)
        def _(event) -> None:
            self.submit_input()

        @bindings.add("c-c")
        def _(event) -> None:
            self.status_line = '输入\u201c退出\u201d结束'
            self.invalidate()

        @bindings.add("y", filter=permission_open)
        def _(event) -> None:
            if self.permission_future and not self.permission_future.done():
                self.permission_future.set_result("allow")
                self.clear_permission()

        @bindings.add("n", filter=permission_open)
        def _(event) -> None:
            if self.permission_future and not self.permission_future.done():
                self.permission_future.set_result("deny")
                self.clear_permission()

        return Application(
            layout=Layout(root, focused_element=self.input_buffer),
            key_bindings=bindings,
            full_screen=True,
            mouse_support=True,
            style=Style.from_dict(
                {
                    "header": "bold",
                    "dim": "ansibrightblack",
                    "user": USER_INPUT_COLOR,
                    "guidance": USER_INPUT_COLOR,
                    "guidance.hint": "ansibrightblack",
                    "assistant": "",
                    "event": "ansibrightblack",
                    "event.denied": "ansired",
                    "status": "ansibrightblack",
                    "prompt": USER_INPUT_COLOR,
                    "permission": "#FFE826 bold",
                    "permission.border": "#FFE826 bold",
                    "logo.b": "#cf916b",
                    "logo.a": "#ffffff",
                    "logo.e": "#000000",
                    "loading": "#40E95C",
                    "info.title": "bold",
                    "info.label": USER_INPUT_COLOR,
                    "info.value": "",
                    "info.hint": "ansibrightblack",
                }
            ),
            refresh_interval=0.1,
        )

    async def run(self) -> None:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
        await self.app.run_async()

    def submit_input(self) -> None:
        if self.permission_request is not None:
            return
        text = self.input_buffer.text.strip()
        self.input_buffer.text = ""
        if not text:
            return
        if text == "退出":
            self.app.exit()
            return
        if self.generating_task and not self.generating_task.done():
            self.add_guidance(text)
            self.invalidate()
            return

        if text.startswith("/"):
            self._send_user_message(
                text,
                is_first_message=not self.messages,
                display_user=False,
            )
            return

        self._send_user_message(text, is_first_message=not self.messages)

    def add_guidance(self, text: str) -> None:
        self.guidance_queue.append(text)
        runtime = getattr(self, "runtime", None)
        if runtime is not None:
            runtime.add_guidance(text)
        elif hasattr(self.session, "add_guidance"):
            self.session.add_guidance(text)
        self.messages.append(ChatMessage("guidance", text))
        self.output_window.user_scrolled_away = False
        self._waiting = True
        self.status_line = f"思考中... · 已加入 {len(self.guidance_queue)} 条引导"
        self.invalidate()

    def _send_user_message(
        self,
        text: str,
        *,
        is_first_message: bool = False,
        display_user: bool = True,
    ) -> None:
        self.output_window.user_scrolled_away = False
        if display_user:
            self.messages.append(ChatMessage("user", text))
        self.current_answer = ""
        self._waiting = True
        self.status_line = "思考中..."
        self.generating_task = asyncio.create_task(
            self.generate(text, is_first_message=is_first_message)
        )
        self.invalidate()

    async def generate(self, text: str, *, is_first_message: bool = False) -> None:
        try:
            runtime = getattr(self, "runtime", None)
            if runtime is None:
                stream = self.session.stream_chat(text)
            else:
                stream = runtime.submit(text, is_first_message=is_first_message)
            async for event in stream:
                if isinstance(event, dict):
                    event_type = event.get("type")
                    content = event.get("content", "")
                    role = event.get("role")
                else:
                    event_type = event.type
                    content = event.content
                    role = event.role
                if event_type in ("text", "assistant_delta") and content:
                    self.current_answer += content
                    self._waiting = False
                elif event_type == "status" and content:
                    if content == "正在处理引导内容":
                        self.guidance_queue.clear()
                        self.messages.append(ChatMessage("event", content))
                        self.output_window.user_scrolled_away = False
                    self.status_line = f"↳ {content}"
                    self._waiting = True
                elif event_type in ("message", "local_message") and content:
                    self.messages.append(ChatMessage(role or "event", content))
                    self.output_window.user_scrolled_away = False
                self.invalidate()
            if self.current_answer:
                self.messages.append(ChatMessage("assistant", self.current_answer))
            self.current_answer = ""
            self.status_line = "输入提示词继续对话"
        except Exception as exc:
            self.current_answer = ""
            self.messages.append(ChatMessage("assistant", f"[错误]: {exc}"))
            self.status_line = "出错"
        finally:
            self.generating_task = None
            self.app.layout.focus(self.input_buffer)
            self.invalidate()

    async def request_permission(self, request: PermissionRequest) -> PermissionScope:
        loop = asyncio.get_running_loop()
        self.permission_request = request
        self.permission_future = loop.create_future()
        self.permission_deadline = time.monotonic() + PERMISSION_TIMEOUT_SECONDS
        self._waiting = True
        self.status_line = "等待权限确认"
        self.invalidate()

        timeout_task = asyncio.create_task(self.permission_timeout())
        try:
            result = await self.permission_future
            self.add_permission_record(request, result)
            return result
        finally:
            timeout_task.cancel()
            self.clear_permission()

    async def permission_timeout(self) -> None:
        await asyncio.sleep(PERMISSION_TIMEOUT_SECONDS)
        if self.permission_future and not self.permission_future.done():
            self.permission_future.set_result("deny")

    def clear_permission(self) -> None:
        self.permission_request = None
        self.permission_future = None
        self.permission_deadline = None
        self.status_line = "权限申请已结束"
        self.app.layout.focus(self.input_buffer)
        self.invalidate()

    def add_permission_record(
        self,
        request: PermissionRequest,
        result: PermissionScope,
    ) -> None:
        result_label = "已允许" if result == "allow" else "已拒绝"
        self.messages.append(
            ChatMessage(
                "event" if result == "allow" else "event_denied",
                (
                    f"权限申请：{request.tool_name} / "
                    f"{self.format_operation(request.operation)} / {result_label}"
                ),
            )
        )

    def startup_info_lines(self, info_width: int) -> list[str]:
        """返回启动页信息行，路径超长时从左截断保留尾部。"""
        return [
            "opendog",
            "",
            f"Version   {self.status.version}",
            f"Agent     {self.status.agent_name}",
            f"Model     {self.status.model}",
            f"Workdir   {self.short_path(self.status.working_dir, info_width - 11)}",
            f"Workspace {self.short_path(self.status.workspace_root, info_width - 10)}",
            f"Skills    {self.status.skill_count} available",
            f"Tools     {self.status.tool_count} total",
            f"MCP       {self.status.mcp_configured} configured",
            '输入提示词开始 · 输入\u201c退出\u201d结束',
        ]

    def pixel_logo_row(self, row: str) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        for cell in row:
            if cell == ".":
                fragments.append(("", "  "))
            elif cell == "A":
                fragments.append(("class:logo.a", "██"))
            elif cell == "B":
                fragments.append(("class:logo.b", "██"))
            elif cell == "E":
                fragments.append(("class:logo.e", "██"))
        return fragments

    def render_output(self) -> FormattedText:
        fragments: list[tuple[str, str]] = []
        # 启动页 header
        fragments.extend(self._build_header_fragments())
        fragments.append(("", "\n"))
        # 对话消息——正常时间顺序，最新的在最下面
        for message in self.visible_messages():
            if message.role == "guidance":
                self.render_guidance_message(fragments, message.content)
                continue
            prefix = self.message_prefix(message.role)
            style = self.message_style(message.role)
            content_width = CHAT_WIDTH - display_width(prefix)
            continuation = " " * display_width(prefix)
            for index, line in enumerate(self.wrap_text(message.content, content_width)):
                fragments.append((style, fit_text((prefix if index == 0 else continuation) + line, CHAT_WIDTH)))
                fragments.append(("", "\n"))
            fragments.append(("", "\n"))
        # 当前正在生成的回答
        if self.current_answer:
            for index, line in enumerate(self.wrap_text(self.current_answer, CHAT_WIDTH - 2)):
                fragments.append(("class:assistant", fit_text(("● " if index == 0 else "  ") + line, CHAT_WIDTH)))
                fragments.append(("", "\n"))
        # 自动滚底：用户未手动滚走时跟随到底部
        if not self.output_window.user_scrolled_away:
            self.output_window.shared_scroll = 999_999_999
        return fragments

    def render_guidance_message(self, fragments: list[tuple[str, str]], content: str) -> None:
        prefix = ">: "
        content_width = CHAT_WIDTH - display_width(prefix)
        continuation = " " * display_width(prefix)
        for index, line in enumerate(self.wrap_text(content, content_width)):
            fragments.append(
                (
                    "class:guidance",
                    fit_text((prefix if index == 0 else continuation) + line, CHAT_WIDTH),
                )
            )
            fragments.append(("", "\n"))
        fragments.append(("class:guidance.hint", fit_text("  · 已加入引导", CHAT_WIDTH)))
        fragments.append(("", "\n\n"))

    def _build_header_fragments(self) -> list[tuple[str, str]]:
        fragments: list[tuple[str, str]] = []
        fragments.append(("class:header", "┏" + "━" * (CHAT_WIDTH - 2) + "┓"))
        fragments.append(("", "\n"))
        info_lines = self.startup_info_lines(HEADER_INFO_WIDTH)
        for row_index, logo_row in enumerate(PIXEL_LOGO):
            fragments.append(("class:header", "┃ "))
            fragments.extend(self.pixel_logo_row(logo_row))
            fragments.append(("class:dim", HEADER_DIVIDER))
            info = info_lines[row_index] if row_index < len(info_lines) else ""
            # 按行次应用不同颜色方案
            if row_index == 0:
                # 标题行
                fragments.append(("class:info.title", fit_text(info, HEADER_INFO_WIDTH)))
                fragments.append(("class:header", " ┃"))
            elif row_index == len(info_lines) - 1:
                # 底部提示行
                fragments.append(("class:info.hint", fit_text(info, HEADER_INFO_WIDTH)))
                fragments.append(("class:header", " ┃"))
            elif info:
                # 数据行：拆分为标签和值分别着色
                match = re.match(r"(\S+)\s+(.+)", info)
                if match:
                    label, value = match.group(1), match.group(2)
                    fragments.append(("class:info.label", label + " "))
                    fragments.append(("class:info.value", fit_text(value, HEADER_INFO_WIDTH - display_width(label) - 1)))
                    fragments.append(("class:header", " ┃"))
                else:
                    fragments.append(("class:header", fit_text(info, HEADER_INFO_WIDTH) + " ┃"))
            else:
                fragments.append(("class:header", fit_text(info, HEADER_INFO_WIDTH) + " ┃"))
            fragments.append(("", "\n"))
        fragments.append(("class:header", "┗" + "━" * (CHAT_WIDTH - 2) + "┛"))
        fragments.append(("", "\n"))
        return fragments

    def message_prefix(self, role: str) -> str:
        if role == "user":
            return ">: "
        if role == "guidance":
            return ">: "
        if role == "event":
            return "· "
        return "● "

    def message_style(self, role: str) -> str:
        if role == "user":
            return "class:user"
        if role == "guidance":
            return "class:guidance"
        if role == "event":
            return "class:event"
        if role == "event_denied":
            return "class:event.denied"
        return "class:assistant"

    def render_permission(self) -> FormattedText:
        if self.permission_request is None:
            return [("", "")]
        remaining = self.permission_remaining()
        request = self.permission_request
        content = [
            "┏" + "━" * (CHAT_WIDTH - 2) + "┓",
            self.pad_line(f"权限申请 · {remaining}s 后自动拒绝"),
            self.pad_line(f"工具：{request.tool_name}"),
            self.pad_line(f"操作：{self.format_operation(request.operation)}"),
            self.pad_line(f"目标：{request.target}"),
            self.pad_line(f"原因：{request.reason}"),
            self.pad_line("按 y 允许，按 n 拒绝"),
            "┗" + "━" * (CHAT_WIDTH - 2) + "┛",
        ]
        return self.lines_to_fragments(content, "class:permission")

    def render_status(self) -> FormattedText:
        # MCP tools still loading in background?
        if self._mcp_manager is not None and self._mcp_manager.startup_in_progress():
            done, total = self._mcp_manager.startup_done_count()
            idx = int(time.monotonic() * 10) % len(SPINNER_FRAMES)
            spinner = SPINNER_FRAMES[idx]
            return [
                ("class:loading", spinner + " "),
                ("class:status", fit_text(f"MCP loading ({done}/{total})", CHAT_WIDTH - 2)),
            ]

        loading = self.generating_task is not None and (
            self._waiting or self.status_line.startswith("\u21b3")
        )
        if loading:
            idx = int(time.monotonic() * 10) % len(SPINNER_FRAMES)
            spinner = SPINNER_FRAMES[idx]
            return [
                ("class:loading", spinner + " "),
                ("class:status", fit_text(self.status_line, CHAT_WIDTH - 2)),
            ]
        return [("class:status", fit_text(self.status_line, CHAT_WIDTH))]

    def visible_messages(self) -> list[ChatMessage]:
        return self.messages[-30:]

    def wrap_text(self, text: str, width: int) -> list[str]:
        result: list[str] = []
        for raw_line in text.splitlines() or [""]:
            if not raw_line:
                result.append("")
                continue
            result.extend(wrap_display_width(raw_line, width))
        return result

    def pad_line(self, text: str) -> str:
        return "┃ " + fit_text(text, CHAT_WIDTH - 4) + " ┃"

    def lines_to_fragments(
        self,
        lines: list[str],
        style: Optional[str] = None,
        styled_lines: Optional[list[tuple[str, str]]] = None,
    ) -> FormattedText:
        fragments = []
        if styled_lines is not None:
            for line_style, text in styled_lines:
                fragments.append((line_style, fit_text(text, CHAT_WIDTH)))
                fragments.append(("", "\n"))
            return fragments
        for line in lines:
            fragments.append((style or "", fit_text(line, CHAT_WIDTH)))
            fragments.append(("", "\n"))
        return fragments

    def permission_remaining(self) -> int:
        if self.permission_deadline is None:
            return 0
        return max(0, int(self.permission_deadline - time.monotonic() + 0.999))

    def short_path(self, path, max_width: int = 0) -> str:
        """返回简短路径，超出 max_width 时从左侧用 ... 截断。"""
        parts = [path.name]
        current = path.parent
        while True:
            name = current.name
            if not name:
                break
            parts.append(name)
            current = current.parent
        parts.reverse()
        result = "/".join(parts)
        if max_width <= 0:
            return result
        if display_width(result) <= max_width:
            return result
        # 从左边删分量，保留尾部
        for i in range(1, len(parts)):
            result = ".../" + "/".join(parts[i:])
            if display_width(result) <= max_width:
                return result
        return "..." + result[-(max_width - 3):]

    def format_operation(self, operation: str) -> str:
        labels = {
            "read_path": "读取路径",
            "write_path": "写入路径",
            "run_shell": "执行命令",
        }
        return labels.get(operation, operation)

    def invalidate(self) -> None:
        self.app.invalidate()


def display_width(text: str) -> int:
    return sum(char_width(char) for char in text)


def char_width(char: str) -> int:
    if unicodedata.combining(char):
        return 0
    if unicodedata.east_asian_width(char) in {"F", "W"}:
        return 2
    return 1


def fit_text(text: str, width: int) -> str:
    output = []
    used = 0
    for char in text:
        char_display_width = char_width(char)
        if used + char_display_width > width:
            break
        output.append(char)
        used += char_display_width
    return "".join(output) + " " * (width - used)


def wrap_display_width(text: str, width: int) -> list[str]:
    width = max(1, width)
    lines: list[str] = []
    current: list[str] = []
    used = 0

    for char in text:
        char_display_width = char_width(char)
        if used and used + char_display_width > width:
            lines.append("".join(current))
            current = []
            used = 0
        current.append(char)
        used += char_display_width

    if current:
        lines.append("".join(current))
    return lines or [""]

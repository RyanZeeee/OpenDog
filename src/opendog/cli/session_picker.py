"""启动时会话选择器 —— 在 TuiChatLoop 前独立运行，让用户选择恢复或新建会话。"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style

from opendog.core.session_store import SessionIndexEntry, SessionStore
from opendog.cli.tui import fit_text

SESSION_PICKER_WIDTH = 60

HIGHLIGHT_STYLE = "class:highlight"


def _format_entry_content(entry: SessionIndexEntry, selected: bool) -> str:
    """格式化单个会话条目的内容文本（不含边框）。"""
    cursor = "→" if selected else " "
    date_str = entry.updated_at[:16].replace("T", " ")
    title = entry.title or "(空对话)"
    line = f"  {cursor}  {date_str}  {title}  {entry.message_count} 条消息"
    inner_width = SESSION_PICKER_WIDTH - 4
    return fit_text(line, inner_width)


def select_session_sync(store: SessionStore, agent_name: str) -> Optional[str]:
    """同步入口，内部创建自己的 event loop。"""
    try:
        return asyncio.get_event_loop().run_until_complete(
            select_session(store, agent_name)
        )
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(select_session(store, agent_name))
        finally:
            loop.close()


async def select_session(
    store: SessionStore, agent_name: str
) -> Optional[str]:
    entries = store.load_index()
    if not entries:
        return None

    selected_index = 0
    deleted = False
    confirm_delete = False

    def _build_fragments():
        fragments: list[tuple[str, str]] = []

        # 顶边框
        fragments.append(("class:border", "┏" + "━" * (SESSION_PICKER_WIDTH - 2) + "┓"))
        fragments.append(("", "\n"))

        if confirm_delete:
            fragments.append(("class:border", "┃ "))
            fragments.append(("class:warn", fit_text("确认删除该会话？(y = 确认，n = 取消)", SESSION_PICKER_WIDTH - 4)))
            fragments.append(("class:border", " ┃"))
        else:
            fragments.append(("class:border", "┃ "))
            fragments.append(("class:border bold", fit_text("Recent Sessions", SESSION_PICKER_WIDTH - 4)))
            fragments.append(("class:border", " ┃"))
        fragments.append(("", "\n"))

        fragments.append(("class:border", "┃ "))
        fragments.append(("class:dim", fit_text("↑↓ 选择  Enter 恢复  n 新建  d 删除  q 退出", SESSION_PICKER_WIDTH - 4)))
        fragments.append(("class:border", " ┃"))
        fragments.append(("", "\n"))

        # 空行分隔
        inner = " " * (SESSION_PICKER_WIDTH - 4)
        fragments.append(("class:border", "┃ " + inner + " ┃"))
        fragments.append(("", "\n"))

        for i, entry in enumerate(entries):
            content = _format_entry_content(entry, i == selected_index)
            if i == selected_index:
                content_style = HIGHLIGHT_STYLE
            else:
                content_style = ""
            fragments.append(("class:border", "┃ "))
            fragments.append((content_style, content))
            fragments.append(("class:border", " ┃"))
            fragments.append(("", "\n"))

        # 底边框
        fragments.append(("class:border", "┗" + "━" * (SESSION_PICKER_WIDTH - 2) + "┛"))
        fragments.append(("", "\n"))
        return FormattedText(fragments)

    control = FormattedTextControl(_build_fragments)
    window = Window(control, always_hide_cursor=True)

    bindings = KeyBindings()

    @bindings.add("up", eager=True)
    def _move_up(event):
        nonlocal selected_index, confirm_delete
        confirm_delete = False
        if selected_index > 0:
            selected_index -= 1
        event.app.invalidate()

    @bindings.add("down", eager=True)
    def _move_down(event):
        nonlocal selected_index, confirm_delete
        confirm_delete = False
        if selected_index < len(entries) - 1:
            selected_index += 1
        event.app.invalidate()

    @bindings.add("enter", eager=True)
    def _select(event):
        nonlocal confirm_delete
        if confirm_delete:
            confirm_delete = False
            event.app.invalidate()
            return
        event.app.exit(result=entries[selected_index].id)

    @bindings.add("n", eager=True)
    def _new(event):
        nonlocal confirm_delete
        if confirm_delete:
            confirm_delete = False
            event.app.invalidate()
            return
        event.app.exit(result=None)

    @bindings.add("q", eager=True)
    @bindings.add("escape", eager=True)
    def _quit(event):
        nonlocal confirm_delete
        if confirm_delete:
            confirm_delete = False
            event.app.invalidate()
            return
        event.app.exit(result=None)

    @bindings.add("d", eager=True)
    def _delete_request(event):
        nonlocal confirm_delete
        if confirm_delete:
            return
        if entries:
            confirm_delete = True
            event.app.invalidate()

    @bindings.add("y", eager=True)
    def _confirm_delete(event):
        nonlocal confirm_delete, deleted, selected_index
        if not confirm_delete:
            return
        confirm_delete = False
        deleted = True
        entry = entries[selected_index]
        store.remove_session(entry.id)
        entries.remove(entry)
        if selected_index >= len(entries) and entries:
            selected_index -= 1
        if not entries:
            event.app.exit(result=None)
        else:
            event.app.invalidate()

    app = Application(
        layout=Layout(HSplit([window])),
        key_bindings=bindings,
        full_screen=True,
        style=Style.from_dict(
            {
                "border": "#ffffff",
                "highlight": "bg:#444444 bold",
                "dim": "ansibrightblack",
                "warn": "ansired bold",
            }
        ),
    )

    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    result = await app.run_async()
    return result


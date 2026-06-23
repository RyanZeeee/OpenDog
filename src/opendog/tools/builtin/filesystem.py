from __future__ import annotations

from typing import Any

from opendog.tools.base import tool


@tool(
    name="read",
    description="读取文本文件内容。可通过 offset 参数分段读取大文件。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要读取的文件路径。"},
            "offset": {
                "type": "integer",
                "description": "从第几个字符开始读（0-based）。默认 0 即从头读。",
            },
        },
        "required": ["path"],
    },
)
async def read_file(path: str, session: Any, offset: int = 0) -> str:
    try:
        file_path = await session.resolve_read_path(path, tool_name="read")
        content = file_path.read_text(encoding="utf-8")
        if offset:
            content = content[offset:]
        if file_path.name == "SKILL.md" and hasattr(session, "activate_skill_from_path"):
            session.activate_skill_from_path(file_path)
        return content
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as exc:
        return f"Error: Failed to read {path}: {exc}"


@tool(
    name="write",
    description=(
        "把文本内容写入文件。如果文件不存在，会自动创建。"
        "这是创建或覆盖文本文件的首选工具，支持多行和较长内容；"
        "如果内容太长导致失败，先用本工具写第一段，再用 append 追加后续段；"
        "不要改用 bash、Python 或 base64 写大段文件。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要写入的文件路径。"},
            "content": {"type": "string", "description": "要写入文件的文本内容。"},
        },
        "required": ["path", "content"],
    },
)
async def write_file(path: str, content: str, session: Any) -> str:
    try:
        file_path = await session.resolve_write_path(path, tool_name="write")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        if hasattr(session, "record_successful_write"):
            session.record_successful_write(file_path)
        return f"Wrote {len(content)} characters to {file_path}."
    except Exception as exc:
        return f"Error: Failed to write {path}: {exc}"


@tool(
    name="append",
    description=(
        "把文本内容追加到文件末尾。用于长内容分段写入：write 写第一段，append 写后续段。"
        "如果文件不存在，会自动创建。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要追加内容的文件路径。"},
            "content": {"type": "string", "description": "要追加到文件末尾的文本内容。"},
        },
        "required": ["path", "content"],
    },
)
async def append_file(path: str, content: str, session: Any) -> str:
    try:
        file_path = await session.resolve_write_path(path, tool_name="append")
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as file:
            file.write(content)
        if hasattr(session, "record_successful_write"):
            session.record_successful_write(file_path)
        return f"Appended {len(content)} characters to {file_path}."
    except Exception as exc:
        return f"Error: Failed to append {path}: {exc}"


@tool(
    name="edit",
    description="替换文本文件中的内容。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要编辑的文件路径。"},
            "old_text": {"type": "string", "description": "需要被替换的原文本。"},
            "new_text": {"type": "string", "description": "替换后的新文本。"},
        },
        "required": ["path", "old_text", "new_text"],
    },
)
async def edit_file(path: str, old_text: str, new_text: str, session: Any) -> str:
    try:
        file_path = await session.resolve_write_path(path, tool_name="edit")
        content = file_path.read_text(encoding="utf-8")
        if old_text not in content:
            return f"Error: Text to replace was not found in {path}."

        updated = content.replace(old_text, new_text, 1)
        file_path.write_text(updated, encoding="utf-8")
        return f"Edited {path}."
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as exc:
        return f"Error: Failed to edit {path}: {exc}"


@tool(
    name="multiedit",
    description=(
        "对同一个文本文件按顺序执行多处替换。适合一次修改多个位置；"
        "如果任意 old_text 找不到，整个文件不会被写入。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "要编辑的文件路径。"},
            "edits": {
                "type": "array",
                "description": "按顺序执行的替换列表。",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_text": {
                            "type": "string",
                            "description": "需要被替换的原文本。",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "替换后的新文本。",
                        },
                    },
                    "required": ["old_text", "new_text"],
                },
            },
        },
        "required": ["path", "edits"],
    },
)
async def multiedit_file(path: str, edits: list[dict[str, str]], session: Any) -> str:
    try:
        if not edits:
            return "Error: edits must contain at least one replacement."

        file_path = await session.resolve_write_path(path, tool_name="multiedit")
        content = file_path.read_text(encoding="utf-8")
        updated = content

        for index, edit in enumerate(edits, start=1):
            old_text = edit.get("old_text", "")
            new_text = edit.get("new_text", "")
            if not old_text:
                return f"Error: edits[{index}] old_text must not be empty."
            if old_text not in updated:
                return f"Error: edits[{index}] old_text was not found in {path}."
            updated = updated.replace(old_text, new_text, 1)

        file_path.write_text(updated, encoding="utf-8")
        if hasattr(session, "record_successful_write"):
            session.record_successful_write(file_path)
        return f"Applied {len(edits)} edits to {path}."
    except FileNotFoundError:
        return f"Error: File not found: {path}"
    except Exception as exc:
        return f"Error: Failed to multiedit {path}: {exc}"

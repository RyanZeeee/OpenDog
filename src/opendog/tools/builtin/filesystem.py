from __future__ import annotations

from typing import Any

from opendog.tools.base import tool


@tool(
    name="read",
    description="Read the contents of a text file. Use the offset parameter to read large files in chunks.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to read."},
            "offset": {
                "type": "integer",
                "description": "Character offset to start reading from (0-based). Defaults to 0.",
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
        "Write text content to a file, creating the file if it does not exist. "
        "This is the preferred tool for creating or overwriting text files, including multiline and long content. "
        "If the content is too large and the write fails, use this tool for the first chunk and append for later chunks. "
        "Do not switch to bash, Python, or base64 to write large files."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to write."},
            "content": {"type": "string", "description": "Text content to write into the file."},
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
        "Append text content to the end of a file. Use this for chunked long-file writing: write the first chunk with write, then append later chunks. "
        "Creates the file if it does not exist."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to append to."},
            "content": {"type": "string", "description": "Text content to append to the end of the file."},
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
    description="Replace content in a text file.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to edit."},
            "old_text": {"type": "string", "description": "Exact original text to replace."},
            "new_text": {"type": "string", "description": "Replacement text."},
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
        "Apply multiple replacements to the same text file in order. Use this when editing several locations at once. "
        "If any old_text is not found, the file will not be written."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Path of the file to edit."},
            "edits": {
                "type": "array",
                "description": "Ordered list of replacements to apply.",
                "items": {
                    "type": "object",
                    "properties": {
                        "old_text": {
                            "type": "string",
                            "description": "Exact original text to replace.",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text.",
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

from __future__ import annotations

import asyncio
from typing import Any

from opendog.tools.base import tool


@tool(
    name="bash",
    description="执行一条 bash 命令，并返回 stdout、stderr 和退出码。",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 bash 命令。"},
        },
        "required": ["command"],
    },
)
async def bash(command: str, session: Any) -> str:
    try:
        allowed, reason, extra_roots, include_user_home = await session.approve_shell_command(command)
        if not allowed:
            return f"Error: Command blocked by permission policy: {reason}"

        process = await asyncio.create_subprocess_exec(
            "/bin/bash",
            "-lc",
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=session.agent.working_dir,
            env=session.permissions.shell_environment(include_user_home=include_user_home),
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        command_line = f"command: {command}\n"
        return (
            command_line +
            f"cwd: {session.agent.working_dir}\n"
            f"exit_code: {process.returncode}\n"
            f"stdout:\n{stdout.decode(errors='replace')}\n"
            f"stderr:\n{stderr.decode(errors='replace')}"
        )
    except asyncio.TimeoutError:
        return f"Error: Command timed out after 30 seconds: {command}"
    except Exception as exc:
        return f"Error: Failed to run command {command}: {exc}"

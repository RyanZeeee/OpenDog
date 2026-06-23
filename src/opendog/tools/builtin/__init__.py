from opendog.tools.builtin.filesystem import (
    append_file,
    edit_file,
    multiedit_file,
    read_file,
    write_file,
)
from opendog.tools.builtin.shell import bash
from opendog.tools.builtin.skills import list_skills

BUILTIN_TOOLS = [
    read_file,
    write_file,
    append_file,
    edit_file,
    multiedit_file,
    bash,
    list_skills,
]

__all__ = ["BUILTIN_TOOLS"]

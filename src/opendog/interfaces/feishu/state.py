from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class FeishuState:
    path: Path

    @classmethod
    def from_workspace(cls, workspace_root: Path) -> "FeishuState":
        return cls(workspace_root / ".runtime" / "feishu_state.json")

    def read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def default_chat_id(self) -> str:
        value = self.read().get("default_chat_id")
        return str(value or "").strip()

    def remember_default_chat(self, chat_id: str) -> None:
        chat_id = chat_id.strip()
        if not chat_id:
            return

        state = self.read()
        if state.get("default_chat_id") == chat_id:
            return

        now = datetime.now().astimezone().isoformat()
        if not state.get("default_chat_id"):
            state["first_seen_at"] = now
        state["default_chat_id"] = chat_id
        state["last_seen_at"] = now

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.path)

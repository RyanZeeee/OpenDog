from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
logger = logging.getLogger(__name__)


@dataclass
class SessionIndexEntry:
    id: str
    agent_name: str
    title: str
    message_count: int
    created_at: str
    updated_at: str


class SessionStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._sessions_dir = self.root / "sessions"
        self._index_path = self.root / "index.jsonl"

    # ── index ──────────────────────────────────────────────

    def load_index(self) -> list[SessionIndexEntry]:
        if not self._index_path.exists():
            return []
        entries: list[SessionIndexEntry] = []
        try:
            for line in self._index_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entries.append(SessionIndexEntry(**data))
                except (json.JSONDecodeError, TypeError) as exc:
                    logger.warning("Skipping corrupted index line: %s", exc)
        except OSError as exc:
            logger.warning("Failed to read index: %s", exc)
            return []

        # 清理孤儿条目（index 有记录但 session 文件不存在）
        valid: list[SessionIndexEntry] = []
        orphan_ids: list[str] = []
        for entry in entries:
            session_file = self._session_path(entry.id)
            if session_file.exists():
                valid.append(entry)
            else:
                orphan_ids.append(entry.id)
        if orphan_ids:
            logger.info("Cleaning %d orphan index entries", len(orphan_ids))
            self._rewrite_index(valid)
        valid.sort(key=lambda e: e.updated_at, reverse=True)
        return valid

    def upsert_index(self, entry: SessionIndexEntry) -> None:
        entries = self.load_index()
        found = False
        for i, existing in enumerate(entries):
            if existing.id == entry.id:
                entries[i] = entry
                found = True
                break
        if not found:
            entries.append(entry)
        entries.sort(key=lambda e: e.updated_at, reverse=True)
        self._rewrite_index(entries)

    def remove_from_index(self, session_id: str) -> None:
        entries = self.load_index()
        entries = [e for e in entries if e.id != session_id]
        self._rewrite_index(entries)

    def _rewrite_index(self, entries: list[SessionIndexEntry]) -> None:
        self._ensure_dir(self.root)
        lines: list[str] = []
        for entry in entries:
            lines.append(
                json.dumps(
                    {
                        "id": entry.id,
                        "agent_name": entry.agent_name,
                        "title": entry.title,
                        "message_count": entry.message_count,
                        "created_at": entry.created_at,
                        "updated_at": entry.updated_at,
                    },
                    ensure_ascii=False,
                )
            )
        self._index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # ── messages ───────────────────────────────────────────

    def load_messages(self, session_id: str) -> list[dict]:
        path = self._session_path(session_id)
        if not path.exists():
            return []
        messages: list[dict] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    messages.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "Skipping corrupted message in %s: %s", session_id, exc
                    )
        except OSError as exc:
            logger.warning("Failed to read session %s: %s", session_id, exc)
            return []
        return messages

    def append_message(self, session_id: str, message: dict) -> None:
        self._ensure_dir(self._sessions_dir)
        path = self._session_path(session_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def save_messages(self, session_id: str, messages: list[dict]) -> None:
        self._ensure_dir(self._sessions_dir)
        path = self._session_path(session_id)
        lines: list[str] = []
        for m in messages:
            if m.get("role") == "tool":
                continue
            if m.get("role") == "assistant" and m.get("tool_calls"):
                m = {k: v for k, v in m.items() if k != "tool_calls"}
            lines.append(json.dumps(m, ensure_ascii=False))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def remove_session(self, session_id: str) -> None:
        path = self._session_path(session_id)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Failed to delete session file %s: %s", session_id, exc)
        self.remove_from_index(session_id)

    # ── helpers ────────────────────────────────────────────

    def _session_path(self, session_id: str) -> Path:
        return self._sessions_dir / f"{session_id}.jsonl"

    def _ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

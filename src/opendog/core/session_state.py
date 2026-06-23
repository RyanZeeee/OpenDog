from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from opendog.core.session_store import SessionStore

MAX_HISTORY_TOKENS = 200000
KEEP_RECENT_MESSAGES = 20
SUMMARY_MAX_TOKENS = 8000
SUMMARY_HEADER = "[opendog 历史摘要]"


class SessionState:
    def __init__(
        self,
        system_prompt: str,
        session_id: str,
        max_history_tokens: int = MAX_HISTORY_TOKENS,
        keep_recent_messages: int = KEEP_RECENT_MESSAGES,
        summary_max_tokens: int = SUMMARY_MAX_TOKENS,
        store: Optional["SessionStore"] = None,
        agent_name: str = "",
        created_at: Optional[str] = None,
    ) -> None:
        self.session_id = session_id
        self.system_prompt = system_prompt
        self.messages: list[dict] = []
        self.max_history_tokens = max_history_tokens
        self.keep_recent_messages = keep_recent_messages
        self.summary_max_tokens = summary_max_tokens
        self.store = store
        self.agent_name = agent_name
        self.created_at = created_at or self._now_iso()
        self._title = ""

    def set_system_prompt(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def add_message(self, message: dict) -> None:
        self.messages.append(message)
        # 最新用户消息设为标题
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str) and content.strip():
                self._title = content[:10].strip().replace("\n", " ")
        # 写穿到磁盘（工具结果除外，assistant 的 tool_calls 引用也去掉）
        if self.store and message.get("role") != "tool":
            msg = message
            if message.get("role") == "assistant" and message.get("tool_calls"):
                msg = {k: v for k, v in message.items() if k != "tool_calls"}
            self.store.append_message(self.session_id, msg)
            self.store.upsert_index(self._make_index_entry())

    def load_messages(self, messages: list[dict]) -> None:
        """从磁盘恢复消息，不触发写穿。"""
        self.messages = messages
        # 从最后一条 user 消息恢复标题
        for msg in reversed(messages):
            if msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    self._title = content[:10].strip().replace("\n", " ")
                    break

    def _make_index_entry(self):
        from opendog.core.session_store import SessionIndexEntry

        return SessionIndexEntry(
            id=self.session_id,
            agent_name=self.agent_name,
            title=self._title or "(空对话)",
            message_count=len(self.messages),
            created_at=self.created_at,
            updated_at=self._now_iso(),
        )

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def build_messages(self) -> list[dict]:
        return [{"role": "system", "content": self.system_prompt}, *self.messages]

    def compact_if_needed(
        self,
        max_history_tokens: Optional[int] = None,
        keep_recent_messages: Optional[int] = None,
        summary_max_tokens: Optional[int] = None,
        force: bool = False,
    ) -> str:
        """压缩上下文，返回值：ok / compacted / full / overflow"""
        max_history_tokens = max_history_tokens or self.max_history_tokens
        keep_recent_messages = keep_recent_messages or self.keep_recent_messages
        summary_max_tokens = summary_max_tokens or self.summary_max_tokens

        if not force and self.estimate_messages_tokens(self.messages) <= max_history_tokens:
            return "ok"

        # 第一级：保留最近 N 条，其余压缩成摘要
        keep_start = self.find_safe_keep_start(keep_recent_messages)
        if keep_start <= 0:
            keep_start = len(self.messages)
        if keep_start <= 0:
            return "ok"

        old_messages = self.messages[:keep_start]
        recent_messages = self.messages[keep_start:]
        summary = self.build_history_summary(old_messages, summary_max_tokens)
        self.messages = [{"role": "assistant", "content": summary}, *recent_messages]

        # 第一级压缩后仍超限 → 第二级：全部合并成摘要，不保留最近消息
        if self.estimate_messages_tokens(self.messages) > max_history_tokens:
            summary = self.build_history_summary(self.messages, summary_max_tokens)
            self.messages = [{"role": "assistant", "content": summary}]

            # 第二级后仍然超限 → 上下文溢出
            if self.estimate_messages_tokens(self.messages) > max_history_tokens:
                if self.store:
                    self.store.save_messages(self.session_id, self.messages)
                    self.store.upsert_index(self._make_index_entry())
                return "overflow"

            if self.store:
                self.store.save_messages(self.session_id, self.messages)
                self.store.upsert_index(self._make_index_entry())
            return "full"

        if self.store:
            self.store.save_messages(self.session_id, self.messages)
            self.store.upsert_index(self._make_index_entry())
        return "compacted"

    def find_safe_keep_start(self, keep_recent_messages: int) -> int:
        keep_start = max(0, len(self.messages) - keep_recent_messages)

        while keep_start > 0 and self.messages[keep_start].get("role") == "tool":
            keep_start -= 1

        return keep_start

    def build_history_summary(
        self,
        messages: list[dict],
        summary_max_tokens: int,
    ) -> str:
        previous_summaries: list[str] = []
        user_requests: list[str] = []
        tool_events: list[str] = []
        errors: list[str] = []

        for message in messages:
            role = message.get("role", "")
            content = self.message_content_text(message)

            if role == "assistant" and content.startswith(SUMMARY_HEADER):
                previous_summaries.append(content)
                continue

            if role == "user":
                user_requests.append(self.preview(content, 180))
                continue

            if role == "assistant":
                for tool_call in message.get("tool_calls", []) or []:
                    event = self.describe_tool_call(tool_call)
                    if event:
                        tool_events.append(event)
                continue

            if role == "tool":
                event = self.describe_tool_result(content)
                if event:
                    tool_events.append(event)
                if "error" in content.lower() or "permission denied" in content.lower():
                    errors.append(self.preview(content, 220))

        lines = [
            SUMMARY_HEADER,
            "旧对话已压缩，省略了大段正文和工具参数；需要文件细节时请重新使用 read 读取真实文件。",
        ]
        self.extend_section(lines, "重要错误", errors)
        self.extend_section(lines, "用户请求", user_requests)
        self.extend_section(lines, "工具和文件线索", tool_events)
        self.extend_section(lines, "上一段摘要", previous_summaries)

        return self.truncate_to_estimated_tokens("\n".join(lines), summary_max_tokens)

    def describe_tool_call(self, tool_call: dict) -> str:
        function = tool_call.get("function", {}) or {}
        name = function.get("name", "unknown")
        arguments_text = function.get("arguments", "") or ""
        path = self.extract_path_from_json(arguments_text)
        if path:
            return f"- 调用工具 {name}，目标：{path}"
        return f"- 调用工具 {name}"

    def describe_tool_result(self, content: str) -> str:
        data = self.try_json_loads(content)
        if isinstance(data, dict):
            path = data.get("path") or data.get("target")
            operation = data.get("operation")
            ok = data.get("ok")
            if path:
                prefix = "工具结果"
                if operation:
                    prefix += f" {operation}"
                if ok is False:
                    prefix += " 失败"
                return f"- {prefix}：{path}"
        path = self.extract_path_from_text(content)
        if path:
            return f"- 工具结果提到路径：{path}"
        return ""

    def extract_path_from_json(self, text: str) -> str:
        data = self.try_json_loads(text)
        if not isinstance(data, dict):
            return ""
        path = data.get("path") or data.get("file") or data.get("target")
        return str(path) if path else ""

    def extract_path_from_text(self, text: str) -> str:
        match = re.search(r"(/[^\s\"'<>]+)", text)
        return match.group(1) if match else ""

    def try_json_loads(self, text: str) -> Optional[object]:
        try:
            return json.loads(text)
        except Exception:
            return None

    def extend_section(
        self,
        lines: list[str],
        title: str,
        items: list[str],
    ) -> None:
        if not items:
            return
        lines.append("")
        lines.append(f"## {title}")
        for item in items:
            lines.append(item if item.startswith("- ") else f"- {item}")

    def message_content_text(self, message: dict) -> str:
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False)

    def estimate_messages_tokens(self, messages: list[dict]) -> int:
        return self.estimate_tokens(json.dumps(messages, ensure_ascii=False))

    def estimate_tokens(self, text: str) -> int:
        chinese_chars = 0
        non_chinese_chars = 0
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                chinese_chars += 1
            else:
                non_chinese_chars += 1
        return chinese_chars + max(1, non_chinese_chars // 4)

    def truncate_to_estimated_tokens(self, text: str, max_tokens: int) -> str:
        if self.estimate_tokens(text) <= max_tokens:
            return text

        output: list[str] = []
        current_tokens = 0
        for char in text:
            char_tokens = 1 if "\u4e00" <= char <= "\u9fff" else 0.25
            if current_tokens + char_tokens > max_tokens:
                break
            output.append(char)
            current_tokens += char_tokens
        return "".join(output).rstrip() + "\n[摘要已截断]"

    def preview(self, text: str, max_chars: int) -> str:
        clean = re.sub(r"\s+", " ", text).strip()
        if len(clean) <= max_chars:
            return clean
        return clean[:max_chars].rstrip() + "..."

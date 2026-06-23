from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from opendog.core.agent import Agent
from opendog.core.conversation_runtime import ConversationRuntime
from opendog.core.runtime_event import RuntimeEvent
from opendog.core.session_store import SessionStore
from opendog.core.shared_context import SharedContext
from opendog.interfaces.feishu.client import FeishuClient
from opendog.interfaces.feishu.state import FeishuState

logger = logging.getLogger(__name__)


@dataclass
class FeishuIncomingMessage:
    text: str
    chat_id: str
    message_id: str
    sender_id: str
    chat_type: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class FeishuAdapter:
    def __init__(
        self,
        *,
        context: SharedContext,
        agent: Agent,
        session_store: SessionStore,
        client: FeishuClient,
    ) -> None:
        self.context = context
        self.agent = agent
        self.session_store = session_store
        self.client = client
        self._runtime_cache: dict[str, ConversationRuntime] = {}

    async def handle_message(self, incoming: FeishuIncomingMessage) -> None:
        allow_from = self.context.config.feishu.allow_from
        if allow_from and incoming.sender_id not in allow_from:
            logger.info("Ignored Feishu message from disallowed sender %s", incoming.sender_id)
            return

        FeishuState.from_workspace(self.context.workspace_root).remember_default_chat(
            incoming.chat_id
        )
        session_key = self.session_key(incoming)
        runtime = self.runtime_for_session(session_key)
        chunks: list[str] = []

        def collect(event: RuntimeEvent) -> None:
            if event.type in ("assistant_delta", "local_message"):
                chunks.append(event.content)

        self.context.event_bus.subscribe(
            "*",
            collect,
            session_id=runtime.session_id,
        )
        try:
            async for _ in runtime.submit(incoming.text, source="feishu"):
                pass
        finally:
            self.context.event_bus.unsubscribe(
                "*",
                collect,
                session_id=runtime.session_id,
            )

        reply = "".join(chunks).strip()
        if not reply:
            reply = "我这边没有生成有效回复。"
        self.client.reply_text(incoming.message_id, reply)

    def runtime_for_session(self, session_key: str) -> ConversationRuntime:
        runtime = self._runtime_cache.get(session_key)
        if runtime is not None:
            return runtime

        session = self.agent.create_session(
            session_id=f"feishu-{session_key}",
            session_store=self.session_store,
            resume=True,
        )
        runtime = ConversationRuntime(
            context=self.context,
            agent=self.agent,
            session=session,
            mcp_manager=getattr(session.tools, "_mcp_manager", None),
        )
        self._runtime_cache[session_key] = runtime
        return runtime

    def session_key(self, incoming: FeishuIncomingMessage) -> str:
        if incoming.chat_id:
            return incoming.chat_id.replace(":", "_")
        return incoming.sender_id.replace(":", "_")


def parse_feishu_message(data: Any) -> FeishuIncomingMessage | None:
    payload = _to_dict(data)
    event = _get(data, "event") or _get(payload, "event") or payload
    message = _get(event, "message") or {}
    sender = _get(event, "sender") or {}
    content_raw = _get(message, "content") or "{}"
    try:
        content = json.loads(content_raw) if isinstance(content_raw, str) else content_raw
    except json.JSONDecodeError:
        content = {"text": str(content_raw)}

    text = str(_get(content, "text") or "").strip()
    if not text:
        return None

    sender_id_data = _get(sender, "sender_id") or {}
    sender_id = (
        _get(sender_id_data, "open_id")
        or _get(sender_id_data, "user_id")
        or _get(sender_id_data, "union_id")
        or ""
    )
    return FeishuIncomingMessage(
        text=text,
        chat_id=str(_get(message, "chat_id") or ""),
        message_id=str(_get(message, "message_id") or ""),
        sender_id=str(sender_id),
        chat_type=str(_get(message, "chat_type") or ""),
        raw=payload,
    )


def _get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _to_dict(data: Any) -> dict[str, Any]:
    if isinstance(data, dict):
        return data
    if hasattr(data, "raw"):
        raw = getattr(data, "raw")
        if isinstance(raw, dict):
            return raw
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "__dict__"):
        return dict(data.__dict__)
    return {}


def make_sync_message_handler(
    adapter: FeishuAdapter,
    loop: asyncio.AbstractEventLoop,
) -> Callable[[Any], None]:
    def handle(data: Any) -> None:
        incoming = parse_feishu_message(data)
        if incoming is None:
            return
        future = asyncio.run_coroutine_threadsafe(
            adapter.handle_message(incoming),
            loop,
        )
        future.add_done_callback(_log_task_error)

    return handle


def _log_task_error(future) -> None:
    try:
        future.result()
    except Exception:
        logger.exception("Failed to handle Feishu message")

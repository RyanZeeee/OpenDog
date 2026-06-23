from __future__ import annotations

import asyncio
import concurrent.futures
from dataclasses import dataclass
from typing import AsyncIterator, Optional

from opendog.core.agent import Agent, AgentSession
from opendog.core.runtime_event import RuntimeEvent
from opendog.core.shared_context import SharedContext


@dataclass
class ConversationRuntime:
    """Business flow for one conversation, independent from output adapters.

    TUI remains a direct caller and consumes the yielded events so it can keep
    tight control of focus, streaming text, permission UI, and local state.
    Other interfaces can subscribe to the same events through EventBus.
    """

    context: SharedContext
    agent: Agent
    session: AgentSession
    mcp_manager: Optional[object] = None

    def add_guidance(self, text: str) -> None:
        if hasattr(self.session, "add_guidance"):
            self.session.add_guidance(text)

    @property
    def session_id(self) -> Optional[str]:
        return getattr(self.session, "session_id", None)

    async def submit(
        self,
        text: str,
        *,
        is_first_message: bool = False,
        source: str = "tui",
    ) -> AsyncIterator[RuntimeEvent]:
        await self.publish(
            RuntimeEvent.user_message(
                text,
                session_id=self.session_id,
                source=source,
            )
        )

        if text.startswith("/"):
            handled = False
            registry = self.session.command_registry
            if registry is not None:
                try:
                    result = await registry.dispatch(text, self.session, self.context)
                except Exception as exc:
                    result = f"命令执行出错：{exc}"
                if result is not None:
                    handled = True
                    event = RuntimeEvent.message(
                        "event",
                        f"{text}\n{result}",
                        session_id=self.session_id,
                        source="command",
                    )
                    await self.publish(event)
                    yield event
            if handled:
                return
            event = RuntimeEvent.message(
                "event",
                text,
                session_id=self.session_id,
                source="runtime",
            )
            await self.publish(event)
            yield event

        if self._should_wait_for_mcp(is_first_message):
            event = RuntimeEvent.status(
                "Waiting for MCP tools...",
                session_id=self.session_id,
                source="mcp",
            )
            await self.publish(event)
            yield event
            await self._wait_for_mcp_startup()

        async for event in self.session.stream_chat(text):
            runtime_event = RuntimeEvent.from_agent_event(
                event,
                session_id=self.session_id,
                source="agent",
            )
            await self.publish(runtime_event)
            yield runtime_event

    async def publish(self, event: RuntimeEvent) -> None:
        """Publish a side-channel copy for subscribers; direct callers still use yield."""
        event_bus = getattr(self.context, "event_bus", None)
        if event_bus is not None:
            await event_bus.publish(event)

    def _should_wait_for_mcp(self, is_first_message: bool) -> bool:
        return (
            self.mcp_manager is not None
            and self.mcp_manager.startup_in_progress()
            and is_first_message
        )

    async def _wait_for_mcp_startup(self) -> None:
        if self.mcp_manager is None:
            return
        futures = list(getattr(self.mcp_manager, "_startup_futures", {}).values())
        if not futures:
            return
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: concurrent.futures.wait(futures, timeout=5.0),
            )
        except Exception:
            pass

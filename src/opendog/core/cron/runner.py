from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from opendog.core.agent import Agent
from opendog.core.conversation_runtime import ConversationRuntime
from opendog.core.cron.definition import CronDef
from opendog.core.cron.loader import disable_cron, discover_crons
from opendog.core.cron.scheduler import CronScheduler
from opendog.core.session_store import SessionStore
from opendog.core.shared_context import SharedContext
from opendog.interfaces.feishu.client import FeishuClient
from opendog.interfaces.feishu.state import FeishuState


@dataclass
class CronRunResult:
    cron_id: str
    content: str


class CronRunner:
    def __init__(
        self,
        *,
        context: SharedContext,
        agent: Agent,
        session_store: SessionStore,
        feishu_client: Optional[FeishuClient] = None,
    ) -> None:
        self.context = context
        self.agent = agent
        self.session_store = session_store
        self.feishu_client = feishu_client
        self.crons_dir = context.workspace_root / "crons"
        self.scheduler = CronScheduler(context.workspace_root / ".runtime" / "cron_state.json")

    async def run_forever(self, poll_seconds: int = 60) -> None:
        print("[cron] runner started. Press Ctrl+C to stop.")
        while True:
            await self.tick()
            await asyncio.sleep(poll_seconds)

    async def tick(self, now: Optional[datetime] = None) -> list[CronRunResult]:
        now = now or datetime.now().astimezone()
        crons = discover_crons(self.crons_dir, default_agent=self.context.config.default_agent)
        due = self.scheduler.due_crons(crons, now)
        results: list[CronRunResult] = []
        for item in due:
            cron = item.cron
            print(f"[cron] running {cron.id}")
            content = await self.run_cron(cron)
            self.scheduler.mark_ran(cron.id, item.run_minute)
            if cron.one_off:
                disable_cron(cron)
            await self.deliver(cron, content)
            print(f"[cron] completed {cron.id}")
            results.append(CronRunResult(cron_id=cron.id, content=content))
        return results

    async def run_cron(self, cron: CronDef) -> str:
        session = self.agent.create_session(
            session_id=f"cron-{cron.id}",
            session_store=self.session_store,
            resume=True,
        )
        runtime = ConversationRuntime(
            context=self.context,
            agent=self.agent,
            session=session,
            mcp_manager=getattr(session.tools, "_mcp_manager", None),
        )
        chunks: list[str] = []

        def collect(event) -> None:
            if event.type in ("assistant_delta", "local_message"):
                chunks.append(event.content)

        self.context.event_bus.subscribe("*", collect, session_id=runtime.session_id)
        try:
            async for _ in runtime.submit(cron.prompt, source="cron"):
                pass
        finally:
            self.context.event_bus.unsubscribe("*", collect, session_id=runtime.session_id)

        return "".join(chunks).strip()

    async def deliver(self, cron: CronDef, content: str) -> None:
        if not content:
            return
        deliver_to = cron.deliver_to or {}
        if deliver_to.get("type") != "feishu":
            return
        chat_id = deliver_to.get("chat_id") or FeishuState.from_workspace(
            self.context.workspace_root
        ).default_chat_id()
        if not chat_id or self.feishu_client is None:
            return
        await asyncio.to_thread(self.feishu_client.send_text_to_chat, str(chat_id), content)

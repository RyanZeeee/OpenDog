import unittest
from types import SimpleNamespace

from opendog.core.conversation_runtime import ConversationRuntime
from opendog.core.event_bus import EventBus
from opendog.core.runtime_event import RuntimeEvent


class FakeRegistry:
    async def dispatch(self, text, session, context):
        if text == "/help":
            return "帮助内容"
        return None


class FakeSession:
    def __init__(self) -> None:
        self.command_registry = FakeRegistry()
        self.guidance: list[str] = []
        self.session_id = "session-1"

    def add_guidance(self, text: str) -> None:
        self.guidance.append(text)

    async def stream_chat(self, text: str):
        yield {"type": "status", "content": "调用模型"}
        yield {"type": "text", "content": f"回复:{text}"}


class ConversationRuntimeTest(unittest.IsolatedAsyncioTestCase):
    def make_runtime(self, event_bus=None) -> ConversationRuntime:
        return ConversationRuntime(
            context=SimpleNamespace(event_bus=event_bus) if event_bus else object(),
            agent=object(),
            session=FakeSession(),
        )

    async def test_known_slash_command_returns_local_event(self) -> None:
        runtime = self.make_runtime()
        events = [event async for event in runtime.submit("/help")]

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].type, "local_message")
        self.assertEqual(events[0].role, "event")
        self.assertEqual(events[0].content, "/help\n帮助内容")
        self.assertEqual(events[0].session_id, "session-1")

    async def test_unknown_slash_command_falls_through_to_agent(self) -> None:
        runtime = self.make_runtime()
        events = [event async for event in runtime.submit("/unknown")]

        self.assertEqual(
            events[0],
            RuntimeEvent.message("event", "/unknown", session_id="session-1"),
        )
        self.assertEqual(
            events[1],
            RuntimeEvent.status("调用模型", session_id="session-1", source="agent"),
        )
        self.assertEqual(
            events[2],
            RuntimeEvent.text("回复:/unknown", session_id="session-1", source="agent"),
        )

    async def test_add_guidance_delegates_to_session(self) -> None:
        runtime = self.make_runtime()
        runtime.add_guidance("改成黑白")

        self.assertEqual(runtime.session.guidance, ["改成黑白"])

    async def test_runtime_publishes_events_to_event_bus(self) -> None:
        bus = EventBus()
        seen: list[RuntimeEvent] = []
        bus.subscribe("*", lambda event: seen.append(event), session_id="session-1")
        runtime = self.make_runtime(event_bus=bus)

        events = [event async for event in runtime.submit("你好")]

        self.assertEqual(
            [event.type for event in seen],
            ["user_message", "status", "assistant_delta"],
        )
        self.assertEqual([event.type for event in events], ["status", "assistant_delta"])
        self.assertEqual(seen[0].content, "你好")
        self.assertEqual(seen[0].source, "tui")


class EventBusTest(unittest.IsolatedAsyncioTestCase):
    async def test_publish_calls_sync_and_async_handlers(self) -> None:
        bus = EventBus()
        seen: list[str] = []

        def sync_handler(event: RuntimeEvent) -> None:
            seen.append(f"sync:{event.content}")

        async def async_handler(event: RuntimeEvent) -> None:
            seen.append(f"async:{event.content}")

        bus.subscribe("status", sync_handler)
        bus.subscribe("*", async_handler)

        await bus.publish(RuntimeEvent.status("运行中"))

        self.assertEqual(seen, ["sync:运行中", "async:运行中"])

    async def test_subscribe_can_filter_by_session_id(self) -> None:
        bus = EventBus()
        seen: list[str] = []
        bus.subscribe(
            "status",
            lambda event: seen.append(event.content),
            session_id="session-a",
        )

        await bus.publish(RuntimeEvent.status("A", session_id="session-a"))
        await bus.publish(RuntimeEvent.status("B", session_id="session-b"))

        self.assertEqual(seen, ["A"])


if __name__ == "__main__":
    unittest.main()

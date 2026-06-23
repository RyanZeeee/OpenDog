import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from opendog.core.event_bus import EventBus
from opendog.core.runtime_event import RuntimeEvent
from opendog.interfaces.feishu.adapter import FeishuAdapter, FeishuIncomingMessage, parse_feishu_message
from opendog.interfaces.feishu.state import FeishuState


class FeishuInterfaceTest(unittest.TestCase):
    def test_parse_text_message_event(self) -> None:
        incoming = parse_feishu_message(
            {
                "event": {
                    "sender": {
                        "sender_id": {
                            "open_id": "ou_123",
                        }
                    },
                    "message": {
                        "chat_id": "oc_abc",
                        "message_id": "om_abc",
                        "chat_type": "p2p",
                        "content": '{"text":"你好"}',
                    },
                }
            }
        )

        self.assertIsNotNone(incoming)
        self.assertEqual(incoming.text, "你好")
        self.assertEqual(incoming.chat_id, "oc_abc")
        self.assertEqual(incoming.message_id, "om_abc")
        self.assertEqual(incoming.sender_id, "ou_123")

    def test_parse_ignores_empty_text(self) -> None:
        incoming = parse_feishu_message(
            {
                "event": {
                    "sender": {"sender_id": {"open_id": "ou_123"}},
                    "message": {
                        "chat_id": "oc_abc",
                        "message_id": "om_abc",
                        "content": '{"text":"   "}',
                    },
                }
            }
        )

        self.assertIsNone(incoming)


class FakeClient:
    def __init__(self) -> None:
        self.replies: list[tuple[str, str]] = []

    def reply_text(self, message_id: str, text: str) -> None:
        self.replies.append((message_id, text))


class FakeRuntime:
    session_id = "feishu-session"

    async def submit(self, text: str, source: str = "feishu"):
        await self.context.event_bus.publish(
            RuntimeEvent.message(
                "event",
                "/help\n可用命令",
                session_id=self.session_id,
                source="command",
            )
        )
        return
        yield


class FakeAdapter(FeishuAdapter):
    def __init__(self, context, client) -> None:
        self.context = context
        self.client = client
        self._runtime = FakeRuntime()
        self._runtime.context = context

    def runtime_for_session(self, session_key: str):
        return self._runtime


class FeishuAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_local_message_is_sent_back_to_feishu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = SimpleNamespace(
                workspace_root=Path(tmp),
                config=SimpleNamespace(feishu=SimpleNamespace(allow_from=[])),
                event_bus=EventBus(),
            )
            client = FakeClient()
            adapter = FakeAdapter(context, client)

            await adapter.handle_message(
                FeishuIncomingMessage(
                    text="/help",
                    chat_id="oc_abc",
                    message_id="om_abc",
                    sender_id="ou_123",
                )
            )

            self.assertEqual(client.replies, [("om_abc", "/help\n可用命令")])

    async def test_handle_message_remembers_default_chat_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp)
            context = SimpleNamespace(
                workspace_root=workspace_root,
                config=SimpleNamespace(feishu=SimpleNamespace(allow_from=[])),
                event_bus=EventBus(),
            )
            adapter = FakeAdapter(context, FakeClient())

            await adapter.handle_message(
                FeishuIncomingMessage(
                    text="hi",
                    chat_id="oc_default",
                    message_id="om_abc",
                    sender_id="ou_123",
                )
            )

            self.assertEqual(
                FeishuState.from_workspace(workspace_root).default_chat_id(),
                "oc_default",
            )


if __name__ == "__main__":
    unittest.main()

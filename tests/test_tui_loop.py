import asyncio
import unittest

from prompt_toolkit.buffer import Buffer

from opendog.cli.tui import ChatMessage, TuiChatLoop


class FakeApp:
    def __init__(self) -> None:
        self.layout = FakeLayout()

    def invalidate(self) -> None:
        pass

    def exit(self) -> None:
        pass


class FakeLayout:
    def focus(self, _target) -> None:
        pass


class FakeSession:
    def __init__(self) -> None:
        self.guidance: list[str] = []

    def add_guidance(self, text: str) -> None:
        self.guidance.append(text)

    async def stream_chat(self, text: str):
        yield {"type": "text", "content": f"收到:{text}"}


class SlowFakeSession:
    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.guidance: list[str] = []

    def add_guidance(self, text: str) -> None:
        self.guidance.append(text)

    async def stream_chat(self, text: str):
        await self.release.wait()
        yield {"type": "text", "content": f"收到:{text}"}
        if self.guidance:
            guidance = self.guidance[:]
            self.guidance.clear()
            yield {"type": "status", "content": "正在处理引导内容"}
            yield {"type": "text", "content": f"应用:{'|'.join(guidance)}"}


class FakeOutputWindow:
    def __init__(self) -> None:
        self.user_scrolled_away = False


class TuiChatLoopTest(unittest.IsolatedAsyncioTestCase):
    def make_chat_loop(self, session=None) -> TuiChatLoop:
        chat_loop = object.__new__(TuiChatLoop)
        chat_loop.session = session or FakeSession()
        chat_loop.messages: list[ChatMessage] = []
        chat_loop.status_line = ""
        chat_loop.current_answer = ""
        chat_loop._waiting = False
        chat_loop.guidance_queue = []
        chat_loop.generating_task = None
        chat_loop.permission_request = None
        chat_loop._mcp_manager = None
        chat_loop.app = FakeApp()
        chat_loop.input_buffer = Buffer(multiline=False)
        chat_loop.output_window = FakeOutputWindow()
        return chat_loop

    async def test_submit_input_after_first_turn_finishes(self) -> None:
        chat_loop = self.make_chat_loop()
        chat_loop.input_buffer.text = "第一轮"
        chat_loop.submit_input()
        self.assertIsNotNone(chat_loop.generating_task)
        await chat_loop.generating_task
        self.assertIsNone(chat_loop.generating_task)

        chat_loop.input_buffer.text = "第二轮"
        chat_loop.submit_input()
        self.assertIsNotNone(chat_loop.generating_task)
        await chat_loop.generating_task
        self.assertIsNone(chat_loop.generating_task)

        self.assertEqual(
            [(message.role, message.content) for message in chat_loop.messages],
            [
                ("user", "第一轮"),
                ("assistant", "收到:第一轮"),
                ("user", "第二轮"),
                ("assistant", "收到:第二轮"),
            ],
        )

    async def test_input_during_generation_is_added_as_guidance(self) -> None:
        session = SlowFakeSession()
        chat_loop = self.make_chat_loop(session)

        chat_loop.input_buffer.text = "第一轮"
        chat_loop.submit_input()
        self.assertIsNotNone(chat_loop.generating_task)

        chat_loop.input_buffer.text = "补充方向"
        chat_loop.submit_input()

        self.assertEqual(chat_loop.guidance_queue, ["补充方向"])
        self.assertEqual(session.guidance, ["补充方向"])
        self.assertEqual(chat_loop.messages[-1], ChatMessage("guidance", "补充方向"))
        self.assertIn("已加入 1 条引导", chat_loop.status_line)

        session.release.set()
        await chat_loop.generating_task
        self.assertIsNone(chat_loop.generating_task)
        self.assertEqual(chat_loop.guidance_queue, [])

        self.assertEqual(
            [(message.role, message.content) for message in chat_loop.messages],
            [
                ("user", "第一轮"),
                ("guidance", "补充方向"),
                ("event", "正在处理引导内容"),
                ("assistant", "收到:第一轮应用:补充方向"),
            ],
        )

    async def test_multiple_guidance_items_are_processed_in_order(self) -> None:
        session = SlowFakeSession()
        chat_loop = self.make_chat_loop(session)

        chat_loop.input_buffer.text = "第一轮"
        chat_loop.submit_input()
        chat_loop.input_buffer.text = "引导一"
        chat_loop.submit_input()
        chat_loop.input_buffer.text = "引导二"
        chat_loop.submit_input()

        self.assertEqual(chat_loop.guidance_queue, ["引导一", "引导二"])
        self.assertEqual(session.guidance, ["引导一", "引导二"])
        self.assertIn("已加入 2 条引导", chat_loop.status_line)

        session.release.set()
        await chat_loop.generating_task

        self.assertEqual(
            [
                (message.role, message.content)
                for message in chat_loop.messages
                if message.role in {"event", "user", "assistant"}
            ],
            [
                ("user", "第一轮"),
                ("event", "正在处理引导内容"),
                ("assistant", "收到:第一轮应用:引导一|引导二"),
            ],
        )


if __name__ == "__main__":
    unittest.main()

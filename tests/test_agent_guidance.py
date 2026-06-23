import unittest

from opendog.core.agent import AgentSession


class FakeState:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    def add_message(self, message: dict) -> None:
        self.messages.append(message)


class AgentGuidanceTest(unittest.TestCase):
    def test_consume_guidance_writes_formal_user_message(self) -> None:
        session = object.__new__(AgentSession)
        session.state = FakeState()
        session.pending_guidance = []

        session.add_guidance("改成黑白极简")
        count = session.consume_guidance_into_history()

        self.assertEqual(count, 1)
        self.assertEqual(session.pending_guidance, [])
        self.assertEqual(len(session.state.messages), 1)
        self.assertEqual(session.state.messages[0]["role"], "user")
        self.assertIn("[Current Task Guidance]", session.state.messages[0]["content"])
        self.assertIn("改成黑白极简", session.state.messages[0]["content"])

    def test_consume_multiple_guidance_items_in_one_user_message(self) -> None:
        session = object.__new__(AgentSession)
        session.state = FakeState()
        session.pending_guidance = []

        session.add_guidance("引导一")
        session.add_guidance("引导二")
        count = session.consume_guidance_into_history()

        self.assertEqual(count, 2)
        self.assertEqual(len(session.state.messages), 1)
        content = session.state.messages[0]["content"]
        self.assertIn("- 引导一", content)
        self.assertIn("- 引导二", content)


if __name__ == "__main__":
    unittest.main()

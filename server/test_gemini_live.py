import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

import gemini_live
from gemini_live import GeminiLive


def message(**fields):
    base = {"server_content": None, "tool_call": None, "session_resumption_update": None, "go_away": None}
    base.update(fields)
    return SimpleNamespace(**base)


TURN_COMPLETE = SimpleNamespace(
    model_turn=None,
    input_transcription=None,
    output_transcription=None,
    turn_complete=True,
    interrupted=False,
)


class FakeSession:
    def __init__(self, messages):
        self._messages = messages
        self._served = False

    async def receive(self):
        if self._served:
            # 실제 연결처럼 다음 메시지를 기다린다(테스트가 제너레이터를 닫을 때까지).
            await asyncio.Event().wait()
        self._served = True
        for m in self._messages:
            yield m


class FakeConnect:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, *exc):
        return False


class FakeClient:
    def __init__(self, sessions):
        self._sessions = list(sessions)
        self.configs = []
        self.aio = SimpleNamespace(live=SimpleNamespace(connect=self._connect))

    def _connect(self, model, config):
        self.configs.append(config)
        return FakeConnect(self._sessions.pop(0))


async def first_event(live):
    queues = [asyncio.Queue(), asyncio.Queue(), asyncio.Queue()]
    gen = live.start_session(*queues, audio_output_callback=lambda data: None, setup_config={})
    try:
        return await asyncio.wait_for(gen.__anext__(), timeout=2)
    finally:
        await gen.aclose()


class SessionResumptionTest(unittest.IsolatedAsyncioTestCase):
    def make_live(self, sessions):
        fake = FakeClient(sessions)
        with mock.patch.object(gemini_live.genai, "Client", return_value=fake):
            live = GeminiLive(project_id="p", location="l", model="m")
        return live, fake

    async def test_go_away_reconnects_with_latest_handle(self):
        live, fake = self.make_live([
            FakeSession([
                message(session_resumption_update=SimpleNamespace(resumable=True, new_handle="h1")),
                message(go_away=SimpleNamespace(time_left="10s")),
            ]),
            FakeSession([message(server_content=TURN_COMPLETE)]),
        ])

        event = await first_event(live)

        self.assertEqual(event, {"serverContent": {"turnComplete": True}})
        self.assertEqual(len(fake.configs), 2)
        self.assertIsNone(fake.configs[0].session_resumption.handle)
        self.assertEqual(fake.configs[1].session_resumption.handle, "h1")
        self.assertIsNotNone(fake.configs[0].context_window_compression.sliding_window)

    async def test_go_away_without_handle_does_not_reconnect(self):
        live, fake = self.make_live([
            FakeSession([
                message(go_away=SimpleNamespace(time_left="10s")),
                message(server_content=TURN_COMPLETE),
            ]),
        ])

        event = await first_event(live)

        self.assertEqual(event, {"serverContent": {"turnComplete": True}})
        self.assertEqual(len(fake.configs), 1)


if __name__ == "__main__":
    unittest.main()

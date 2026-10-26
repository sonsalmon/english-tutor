import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai.types import ActivityHandling

from server import barge_in, call_bot


class QuietAnalyzer:
    def voice_confidence(self, window):
        return 0.0


def make_service(**attrs):
    cls = call_bot.live_service_class()
    svc = cls.__new__(cls)
    defaults = dict(
        _barge_in_words=0, _partner_speaking=False, _heard_words=0, _drop_rest_of_turn=False, _waiting_since=None,
        _bot_is_responding=False, _turn_complete_pending_idle=None, _disconnecting=False, _session=None,
        _wait_logged_at=0.0, _wait_peak=0, _wait_frames=0, _wait_loud=0,
    )
    defaults.update(attrs)
    for key, value in defaults.items():
        setattr(svc, key, value)
    return svc


def stub_config(vad_on=True):
    ric = SimpleNamespace(automatic_activity_detection=SimpleNamespace(disabled=not vad_on), activity_handling=None)
    return SimpleNamespace(input_audio_transcription=None, realtime_input_config=ric)


class ConnectionSwitchTest(unittest.IsolatedAsyncioTestCase):
    async def arm(self, env, mode="smalltalk", vad_on=True):
        svc = make_service(call_mode=mode)
        config = stub_config(vad_on)
        parent = call_bot.live_service_class().__mro__[1]
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(barge_in, "make_analyzer", return_value=QuietAnalyzer()), \
                mock.patch.object(parent, "_connection_task_handler", new=AsyncMock()):
            await call_bot.live_service_class()._connection_task_handler(svc, config)
        return svc, config.realtime_input_config.activity_handling

    async def test_defaults_arm_gate_words_and_reengage(self):
        svc, handling = await self.arm({})
        self.assertIsInstance(svc._gate, barge_in.BargeInGate)
        self.assertEqual((handling, svc._barge_in_words, svc._reengage_sec, svc._reengage_max), (ActivityHandling.NO_INTERRUPTION, 3, 10, 2))
        self.assertIsNotNone(svc._voice)

    async def test_reengage_is_chat_only(self):
        for mode in ("mission", "teachback"):
            svc, _ = await self.arm({}, mode=mode)
            self.assertEqual(svc._reengage_sec, 0)
            self.assertIsNone(svc._voice)

    async def test_mode_words_is_todays_path(self):
        svc, handling = await self.arm({"LIVE_BARGE_IN_MODE": "words"})
        self.assertEqual((svc._gate, handling, svc._barge_in_words), (None, ActivityHandling.NO_INTERRUPTION, 3))

    async def test_mode_words_with_zero_words_leaves_gemini_native(self):
        svc, handling = await self.arm({"LIVE_BARGE_IN_MODE": "words", "LIVE_BARGE_IN_WORDS": "0"})
        self.assertEqual((svc._gate, handling, svc._barge_in_words), (None, None, 0))

    async def test_mode_native_arms_nothing(self):
        svc, handling = await self.arm({"LIVE_BARGE_IN_MODE": "native"})
        self.assertEqual((svc._gate, handling, svc._barge_in_words), (None, None, 0))

    async def test_zero_words_means_native_even_in_vad_mode(self):
        svc, handling = await self.arm({"LIVE_BARGE_IN_WORDS": "0"})
        self.assertEqual((svc._gate, handling, svc._barge_in_words), (None, None, 0))

    async def test_local_turn_mode_arms_no_gate(self):
        svc, handling = await self.arm({}, vad_on=False)
        self.assertEqual((svc._gate, handling, svc._barge_in_words), (None, None, 0))

    async def test_reengage_off_and_gate_knob(self):
        svc, _ = await self.arm({"LIVE_SILENCE_REENGAGE_SEC": "0", "LIVE_BARGE_IN_MIN_VOICED_MS": "400"})
        self.assertEqual((svc._reengage_sec, svc._voice, svc._gate.min_voiced_ms), (0, None, 400))


class InterruptTest(unittest.IsolatedAsyncioTestCase):
    async def test_gate_hit_interrupts_the_partner_once(self):
        gate = SimpleNamespace(feed=mock.Mock(return_value=True), run_ms=736)
        svc = make_service(_gate=gate, _partner_speaking=True, _bot_is_responding=True)
        svc.broadcast_interruption = AsyncMock()
        await svc._gate_audio(SimpleNamespace(audio=b"\0" * 640))
        svc.broadcast_interruption.assert_awaited_once()
        self.assertEqual((svc._partner_speaking, svc._drop_rest_of_turn), (False, True))

    async def test_gate_is_not_fed_while_the_partner_is_silent(self):
        gate = SimpleNamespace(feed=mock.Mock(return_value=True), run_ms=0)
        svc = make_service(_gate=gate)
        svc.broadcast_interruption = AsyncMock()
        await svc._gate_audio(SimpleNamespace(audio=b"\0" * 640))
        gate.feed.assert_not_called()
        svc.broadcast_interruption.assert_not_awaited()

    async def test_no_gate_means_no_interrupt(self):
        svc = make_service(_partner_speaking=True)
        svc.broadcast_interruption = AsyncMock()
        await svc._gate_audio(SimpleNamespace(audio=b"\0" * 640))
        svc.broadcast_interruption.assert_not_awaited()


class ReengageTest(unittest.IsolatedAsyncioTestCase):
    def armed(self, **attrs):
        base = dict(_reengage_sec=10, _reengage_max=2, _reengage_count=0, _waiting_since=100.0,
                    _last_learner_voice_at=0.0, _last_reengage_at=0.0)
        base.update(attrs)
        return make_service(**base)

    def test_due_exactly_after_the_silence_window(self):
        svc = self.armed()
        self.assertFalse(svc._reengage_due(109.9))
        self.assertTrue(svc._reengage_due(110.0))

    def test_learner_voice_pushes_the_deadline(self):
        svc = self.armed(_last_learner_voice_at=105.0)
        self.assertFalse(svc._reengage_due(114.9))
        self.assertTrue(svc._reengage_due(115.0))

    def test_not_due_in_the_blocking_states(self):
        for attrs in (dict(_bot_is_responding=True), dict(_partner_speaking=True), dict(_waiting_since=None),
                      dict(_reengage_count=2), dict(_reengage_sec=0), dict(pause_check=lambda: True)):
            self.assertFalse(self.armed(**attrs)._reengage_due(500.0), attrs)

    async def test_reengage_sends_a_turn_ending_prompt_and_rearms_later(self):
        calls = []
        svc = self.armed(on_reengage=lambda count, silent: calls.append((count, silent)))
        svc._session = SimpleNamespace(send_client_content=AsyncMock())
        await svc._reengage(110.0)
        kwargs = svc._session.send_client_content.await_args.kwargs
        self.assertTrue(kwargs["turn_complete"])
        text = kwargs["turns"][0]["parts"][0]["text"]
        self.assertTrue(text.startswith(call_bot.SILENCE_NOTE_PREFIX))
        self.assertIn("10 seconds", text)
        self.assertEqual(calls, [(1, 10.0)])
        self.assertFalse(svc._reengage_due(119.9))
        self.assertTrue(svc._reengage_due(120.0))

    async def test_max_count_stops_further_prompts_until_the_learner_speaks(self):
        svc = self.armed()
        svc._session = SimpleNamespace(send_client_content=AsyncMock())
        await svc._reengage(110.0)
        await svc._reengage(120.0)
        self.assertFalse(svc._reengage_due(999.0))
        svc._voice = SimpleNamespace(feed=lambda audio: call_bot.LEARNER_VOICE_MS)
        svc._waiting_since = time.monotonic()
        svc._note_waiting_audio(SimpleNamespace(audio=(b"\x10\x00" * 320)))
        self.assertEqual(svc._reengage_count, 0)
        self.assertGreater(svc._last_learner_voice_at, 0.0)


if __name__ == "__main__":
    unittest.main()

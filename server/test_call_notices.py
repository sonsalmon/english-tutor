import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google.genai.types import LiveServerMessage
from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, InputAudioRawFrame
from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

from server import call_bot

LOUD = 4000
QUIET = 900  # WAIT_LOUD_PEAK(600)보다는 크고 QUIET_PEAK(2000)보다는 작다


def frame(peak: int) -> InputAudioRawFrame:
    samples = np.full(320, peak, dtype=np.int16)
    return InputAudioRawFrame(audio=samples.tobytes(), sample_rate=16000, num_channels=1)


def transcript(text: str):
    return SimpleNamespace(server_content=SimpleNamespace(input_transcription=SimpleNamespace(text=text)))


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class Harness:
    """네트워크 없이 서비스에 마이크 프레임·봇 프레임·받아쓰기를 넣고, 화면으로 나갈 메시지를 모은다."""

    def __init__(self):
        cls = call_bot.live_service_class()
        self.service = object.__new__(cls)
        s = self.service
        s._barge_in_words, s._partner_speaking, s._heard_words = 0, False, 0
        s._drop_rest_of_turn, s._waiting_since = False, None
        s._wait_logged_at, s._wait_peak, s._wait_frames, s._wait_loud = 0.0, 0, 0, 0
        self.sent = []
        self.clock = FakeClock()
        self.patches = [
            mock.patch.object(call_bot.time, "monotonic", self.clock),
            mock.patch.object(GeminiLiveLLMService, "process_frame", mock.AsyncMock()),
            mock.patch.object(GeminiLiveLLMService, "_handle_msg_input_transcription", mock.AsyncMock()),
            mock.patch.object(cls, "push_frame", self._push),
        ]

    async def _push(self, frame, direction=None):
        self.sent.append(frame.data)

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.patches:
            p.stop()

    def run(self, coro):
        return asyncio.run(coro)

    def bot_stops(self):
        self.run(self.service.process_frame(BotStoppedSpeakingFrame(), None))

    def bot_starts(self):
        self.run(self.service.process_frame(BotStartedSpeakingFrame(), None))

    def mic(self, peak: int, seconds: float, step: float = 0.02):
        for _ in range(int(round(seconds / step))):
            self.clock.now += step
            self.run(self.service.process_frame(frame(peak), None))

    def learner_says(self, text: str):
        self.run(self.service._handle_msg_input_transcription(transcript(text)))


class PureHelpersTest(unittest.TestCase):
    def test_quiet_utterance_needs_audio_and_enough_words(self):
        self.assertIsNone(call_bot.quiet_utterance(0, 5))
        self.assertIsNone(call_bot.quiet_utterance(500, call_bot.QUIET_MIN_WORDS - 1))
        self.assertTrue(call_bot.quiet_utterance(call_bot.QUIET_PEAK - 1, 4))
        self.assertFalse(call_bot.quiet_utterance(call_bot.QUIET_PEAK, 4))

    def test_noisy_wait_has_a_dead_band(self):
        self.assertTrue(call_bot.noisy_wait(call_bot.NOISY_LOUD_PCT))
        self.assertIsNone(call_bot.noisy_wait(70))
        self.assertFalse(call_bot.noisy_wait(10))


class ThinkingNoticeTest(unittest.TestCase):
    def test_thinking_goes_on_once_after_the_learner_stops_and_off_when_the_partner_speaks(self):
        with Harness() as h:
            h.bot_stops()
            h.mic(LOUD, 1.0)
            h.mic(0, call_bot.THINK_AFTER_SEC - 0.5)
            self.assertEqual(h.sent, [])
            h.mic(0, 1.0)
            h.mic(0, 2.0)
            self.assertEqual(h.sent, [{"type": "thinking", "on": True}])
            h.bot_starts()
            self.assertEqual(h.sent[-1], {"type": "thinking", "on": False})
            self.assertEqual(len(h.sent), 2)

    def test_no_thinking_when_the_learner_never_spoke(self):
        with Harness() as h:
            h.bot_stops()
            h.mic(0, 10.0)
            self.assertEqual(h.sent, [])

    def test_thinking_goes_off_when_the_learner_keeps_talking(self):
        with Harness() as h:
            h.bot_stops()
            h.mic(LOUD, 1.0)
            h.mic(0, call_bot.THINK_AFTER_SEC + 0.5)
            self.assertEqual(h.sent, [{"type": "thinking", "on": True}])
            h.mic(LOUD, 1.0)
            self.assertEqual(h.sent[-1], {"type": "thinking", "on": False})

    def test_a_new_partner_turn_resets_the_voice_count(self):
        with Harness() as h:
            h.bot_stops()
            h.mic(LOUD, 0.1)  # 5프레임: 말로 치지 않는다
            h.mic(0, 5.0)
            self.assertEqual(h.sent, [])


class MicLevelNoticeTest(unittest.TestCase):
    def test_two_quiet_utterances_in_a_row_warn_and_a_normal_one_clears(self):
        with Harness() as h:
            for _ in range(2):
                h.bot_stops()
                h.mic(QUIET, 1.0)
                h.learner_says("I went to the store yesterday")
                h.bot_starts()
            quiet = [m for m in h.sent if m["type"] == "mic_level"]
            self.assertEqual([m["state"] for m in quiet], ["quiet"])
            self.assertLess(quiet[0]["db"], -20)
            h.bot_stops()
            h.mic(LOUD, 1.0)
            h.learner_says("I went to the store yesterday")
            self.assertEqual([m["state"] for m in h.sent if m["type"] == "mic_level"], ["quiet", "ok"])

    def test_one_quiet_utterance_or_short_backchannel_does_not_warn(self):
        with Harness() as h:
            h.bot_stops()
            h.mic(QUIET, 1.0)
            h.learner_says("I went to the store yesterday")
            h.bot_stops()
            h.mic(QUIET, 1.0)
            h.learner_says("yeah")
            self.assertEqual([m for m in h.sent if m["type"] == "mic_level"], [])

    def test_steady_loud_mic_while_waiting_warns_and_clears_when_the_partner_speaks(self):
        with Harness() as h:
            h.bot_stops()
            h.mic(LOUD, call_bot.WAIT_LOG_START_SEC + 1.0)
            noisy = [m for m in h.sent if m["type"] == "mic_level"]
            self.assertEqual([m["state"] for m in noisy], ["noisy"])
            h.bot_starts()
            self.assertEqual([m["state"] for m in h.sent if m["type"] == "mic_level"], ["noisy", "ok"])

    def test_silent_wait_never_warns(self):
        with Harness() as h:
            h.bot_stops()
            h.mic(0, call_bot.WAIT_LOG_START_SEC + 7.0)
            self.assertEqual(h.sent, [])


if __name__ == "__main__":
    unittest.main()

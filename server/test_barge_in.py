import asyncio
import os
import unittest
import wave
from pathlib import Path

import numpy as np

from server.audio_gain import InputGainFilter
from server.barge_in import WINDOW_MS, BargeInGate, VoiceRun, make_analyzer

CHUNK = 640  # 20 ms, 16 kHz int16


class LoudMeansVoice:
    """진폭이 3000을 넘는 창만 유성으로 치는 가짜 분석기."""

    def voice_confidence(self, window):
        return 0.9 if np.abs(np.frombuffer(window, np.int16)).max() > 3000 else 0.1


def tone(ms: int, amp: int = 8000) -> bytes:
    t = np.arange(16 * ms) / 16000
    return (np.sin(2 * np.pi * 200 * t) * amp).astype(np.int16).tobytes()


def silence(ms: int) -> bytes:
    return bytes(32 * ms)


def feed_all(gate, pcm: bytes):
    """청크 단위로 넣고 처음 울린 시점(ms)을 돌려준다. 안 울리면 None."""
    for i in range(0, len(pcm), CHUNK):
        if gate.feed(pcm[i:i + CHUNK]):
            return gate.audio_ms
    return None


class BargeInGateTest(unittest.TestCase):
    def gate(self, **kw):
        return BargeInGate(LoudMeansVoice(), **kw)

    def test_fires_once_after_min_voiced_ms(self):
        gate = self.gate()
        fired_at = feed_all(gate, tone(1500))
        self.assertTrue(700 <= fired_at <= 700 + 2 * WINDOW_MS, fired_at)
        self.assertFalse(gate.feed(tone(100)))

    def test_short_reaction_does_not_fire(self):
        self.assertIsNone(feed_all(self.gate(), tone(580) + silence(1000)))

    def test_gap_up_to_bridge_is_bridged(self):
        self.assertIsNotNone(feed_all(self.gate(), tone(400) + silence(160) + tone(400)))

    def test_longer_gap_resets_the_run(self):
        self.assertIsNone(feed_all(self.gate(), tone(400) + silence(300) + tone(400)))

    def test_quiet_audio_below_min_dbfs_never_counts(self):
        class AlwaysVoice:
            def voice_confidence(self, window):
                return 1.0

        gate = BargeInGate(AlwaysVoice())
        self.assertIsNone(feed_all(gate, tone(2000, amp=100)))  # 약 -50 dBFS
        self.assertIsNotNone(feed_all(gate, tone(2000, amp=1000)))  # 약 -30 dBFS

    def test_reset_rearms_the_gate(self):
        gate = self.gate()
        self.assertIsNotNone(feed_all(gate, tone(1000)))
        gate.reset()
        self.assertEqual(gate.run_ms, 0)
        self.assertIsNotNone(feed_all(gate, tone(1000)))

    def test_min_voiced_ms_is_configurable(self):
        self.assertTrue(feed_all(self.gate(min_voiced_ms=300), tone(1000)) <= 300 + 2 * WINDOW_MS)

    def test_odd_sized_chunks_are_buffered(self):
        gate = self.gate()
        pcm = tone(1000)
        fired = any(gate.feed(pcm[i:i + 333]) for i in range(0, len(pcm), 333))
        self.assertTrue(fired)


class VoiceRunTest(unittest.TestCase):
    def test_run_ms_counts_without_level_floor(self):
        run = VoiceRun(LoudMeansVoice(), min_dbfs=None)
        run.feed(tone(320))
        self.assertGreaterEqual(run.run_ms, 300)
        run.feed(silence(400))
        self.assertEqual(run.run_ms, 0)


CLIPS_ROOT = Path(os.environ.get("N4_CLIPS_ROOT", "/Users/sonsalmom/dev/.omo/dag/night-3/replica"))
REACTIONS = ("backchannel_084_688.8s", "backchannel_057_379.1s")  # "Mm.", "Hmm"
INTERRUPTION = "hesitant_092_878.5s"


def load_clip(folder: str, name: str) -> bytes:
    """실제 통화처럼 클립 앞에 0.6 s의 배경 소음(약 -60 dBFS)을 붙여 돌려준다."""
    with wave.open(str(CLIPS_ROOT / folder / f"{name}.wav")) as w:
        assert (w.getframerate(), w.getnchannels()) == (16000, 1)
        lead = (np.random.default_rng(1).standard_normal(16 * 600) * 30).astype(np.int16).tobytes()
        return lead + w.readframes(w.getnframes())


def with_gain(pcm: bytes) -> bytes:
    async def run():
        f = InputGainFilter()
        await f.start(16000)
        return b"".join([await f.filter(pcm[i:i + CHUNK]) for i in range(0, len(pcm), CHUNK)])

    return asyncio.run(run())


@unittest.skipUnless(CLIPS_ROOT.is_dir(), "학습자 클립 폴더 없음(N4_CLIPS_ROOT)")
class RealClipGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.analyzer = make_analyzer()

    def fire(self, pcm: bytes):
        gate = BargeInGate(self.analyzer)
        onset = None
        for i in range(0, len(pcm), CHUNK):
            chunk = pcm[i:i + CHUNK]
            if onset is None and np.abs(np.frombuffer(chunk, np.int16)).max() > 1000:
                onset = gate.audio_ms
            if gate.feed(chunk):
                return onset, gate.audio_ms
        return onset, None

    def variants(self, name):
        for folder in ("learner-clips", "learner-clips-loud"):
            pcm = load_clip(folder, name)
            yield f"{folder} raw", pcm
            yield f"{folder} gain", with_gain(pcm)

    def test_short_reactions_never_fire(self):
        for name in REACTIONS:
            for label, pcm in self.variants(name):
                self.assertIsNone(self.fire(pcm)[1], f"{name} {label}")

    def test_interrupting_sentence_fires_within_0_9_s_of_speech_onset(self):
        for label, pcm in self.variants(INTERRUPTION):
            onset, fired = self.fire(pcm)
            self.assertIsNotNone(fired, label)
            self.assertLessEqual(fired - onset, 900, f"{label}: onset {onset} ms, fired {fired} ms")


if __name__ == "__main__":
    unittest.main()

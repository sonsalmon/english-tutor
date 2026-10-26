import asyncio
import random
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import breath_insert as bi

SR = 24000
BYTES_PER_SEC = SR * 2


def speech(sec: float) -> bytes:
    t = np.arange(int(sec * SR)) / SR
    return (8000 * np.sin(2 * np.pi * 180 * t)).astype(np.int16).tobytes()


def quiet(sec: float) -> bytes:
    return (np.random.RandomState(0).randn(int(sec * SR)) * 15).astype(np.int16).tobytes()


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def planner(clock=None, n_clips=3, spoken=20.0):
    clips = [np.full(int(0.3 * SR), 30.0 * (i + 1)) for i in range(n_clips)]
    p = bi.BreathPlanner(clips, rng=random.Random(1), clock=clock or Clock())
    p.total_speech = spoken
    return p


def learner_spoke(p):
    for _ in range(bi.LEARNER_MIN_LOUD_FRAMES):
        p.learner_audio(4000)
    p.clock.now += 2


def run(p, parts, clock=None):
    out = []
    for pcm in parts:
        out.extend(p.process_audio(pcm, SR))
        if clock is not None:
            clock.now += len(pcm) / BYTES_PER_SEC
    return out


class PlacementTest(unittest.TestCase):
    def test_inserts_before_first_speech_of_an_answer(self):
        clock = Clock()
        p = planner(clock)
        learner_spoke(p)
        p.turn_started()
        out = run(p, [quiet(0.4), speech(1.0)])
        self.assertEqual(len(p.events), 1)
        self.assertEqual(p.events[0]["kind"], "start")
        self.assertEqual(len(b"".join(out)) - len(quiet(0.4) + speech(1.0)), int(0.3 * SR) * 2)
        self.assertEqual(out[0], quiet(0.4))
        self.assertEqual(out[-1], speech(1.0))

    def test_added_time_is_at_most_035_seconds(self):
        p = planner()
        p.clips = [np.full(SR, 50.0)]
        learner_spoke(p)
        p.turn_started()
        out = run(p, [speech(1.0)])
        self.assertLessEqual(len(b"".join(out)) - len(speech(1.0)), int(bi.MAX_ADD_SEC * SR) * 2)

    def test_no_breath_for_an_opener_without_a_learner_turn(self):
        p = planner()
        p.turn_started()
        audio = speech(2.0)
        self.assertEqual(p.process_audio(audio, SR), [audio])
        self.assertEqual(p.events, [])

    def test_never_while_the_learner_speaks(self):
        clock = Clock()
        p = planner(clock)
        learner_spoke(p)
        p.turn_started()
        p.learner_audio(4000)
        self.assertEqual(run(p, [speech(1.0)]), [speech(1.0)])
        p.learner_started()
        self.assertTrue(p.learner_speaking())

    def test_pause_inside_a_long_turn(self):
        clock = Clock()
        p = planner(clock)
        p.turn_started()
        run(p, [speech(5.0)], clock)
        out = run(p, [quiet(0.5), speech(1.0)], clock)
        self.assertEqual([e["kind"] for e in p.events], ["pause"])
        self.assertEqual(len(out), 3)

    def test_short_pause_or_short_turn_gets_no_breath(self):
        for lead, pause in ((5.0, 0.2), (2.0, 0.5)):
            clock = Clock()
            p = planner(clock)
            p.turn_started()
            p.first_onset_done = True
            run(p, [speech(lead)], clock)
            run(p, [quiet(pause), speech(1.0)], clock)
            self.assertEqual(p.events, [], (lead, pause))

    def test_at_most_one_per_fifteen_seconds(self):
        clock = Clock()
        p = planner(clock)
        learner_spoke(p)
        p.turn_started()
        run(p, [speech(5.0)], clock)
        run(p, [quiet(0.5), speech(1.5)], clock)
        run(p, [quiet(0.5), speech(1.5)], clock)
        self.assertEqual(len(p.events), 1)

    def test_rate_stays_near_two_per_partner_minute(self):
        clock = Clock()
        p = planner(clock, spoken=0.0)
        for _ in range(12):
            learner_spoke(p)
            p.turn_started()
            run(p, [quiet(0.2), speech(2.0), quiet(0.5), speech(2.0), quiet(0.5), speech(1.0)], clock)
            p.turn_ended()
        minutes = p.total_speech / 60
        self.assertGreater(minutes, 0.9)
        self.assertLessEqual(p.inserted, bi.TARGET_PER_MIN * minutes + bi.BUDGET_SLACK)
        self.assertGreaterEqual(p.inserted, 1)

    def test_off_or_no_clips_leave_frames_unchanged(self):
        self.assertFalse(bi.breaths_enabled({}))
        self.assertFalse(bi.breaths_enabled({"LIVE_BREATHS": "off"}))
        self.assertTrue(bi.breaths_enabled({"LIVE_BREATHS": "on"}))
        p = bi.BreathPlanner([], clock=Clock())
        learner_spoke(p)
        p.turn_started()
        audio = quiet(0.3) + speech(1.0)
        self.assertEqual(p.process_audio(audio, SR), [audio])

    def test_clip_is_resampled_to_the_stream_rate(self):
        p = planner()
        learner_spoke(p)
        p.turn_started()
        pcm = (np.full(48000, 8000, dtype=np.int16)).tobytes()
        out = p.process_audio(pcm, 48000)
        self.assertEqual(len(b"".join(out)) - len(pcm), int(0.3 * SR) * 2 * 2)


class AssetTest(unittest.TestCase):
    def test_clips_exist_and_are_small(self):
        files = list(bi.ASSET_DIR.glob("*/b*.wav"))
        self.assertGreater(len(files), 0)
        self.assertLess(sum(f.stat().st_size for f in files), 2_000_000)
        for f in files:
            with wave.open(str(f)) as w:
                self.assertEqual((w.getframerate(), w.getnchannels(), w.getsampwidth()), (SR, 1, 2))
                self.assertLessEqual(w.getnframes() / SR, bi.MAX_ADD_SEC)

    def test_unknown_voice_falls_back(self):
        self.assertEqual(len(bi.load_clips("NoSuchVoice")), len(bi.load_clips(bi.FALLBACK_VOICE)))


class ProcessorTest(unittest.TestCase):
    def test_processor_splits_the_audio_frame_and_passes_others(self):
        from pipecat.frames.frames import (
            TTSAudioRawFrame,
            TTSStartedFrame,
            TTSStoppedFrame,
            UserStartedSpeakingFrame,
            UserStoppedSpeakingFrame,
        )
        from pipecat.processors.frame_processor import FrameProcessor

        with tempfile.TemporaryDirectory() as tmp:
            voice_dir = Path(tmp) / "Kore"
            voice_dir.mkdir()
            with wave.open(str(voice_dir / "b01.wav"), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(SR)
                w.writeframes(np.full(int(0.2 * SR), 40, dtype=np.int16).tobytes())
            proc = bi.make_breath_processor("Kore", Path(tmp))
        pushed = []

        async def push(frame, direction=None):
            pushed.append(frame)

        proc.push_frame = push

        async def go():
            with mock.patch.object(FrameProcessor, "process_frame", new=mock.AsyncMock()):
                await proc.process_frame(TTSStartedFrame(), None)
                await proc.process_frame(TTSAudioRawFrame(audio=speech(16.0), sample_rate=SR, num_channels=1), None)
                await proc.process_frame(TTSStoppedFrame(), None)
                pushed.clear()
                await proc.process_frame(UserStartedSpeakingFrame(), None)
                await proc.process_frame(UserStoppedSpeakingFrame(), None)
                await proc.process_frame(TTSStartedFrame(), None)
                audio = quiet(0.3) + speech(0.5)
                await proc.process_frame(TTSAudioRawFrame(audio=audio, sample_rate=SR, num_channels=1), None)

        asyncio.run(go())
        audio_frames = [f for f in pushed if isinstance(f, TTSAudioRawFrame)]
        self.assertEqual(len(pushed), 3 + len(audio_frames))
        self.assertEqual(len(audio_frames), 3)
        self.assertEqual(sum(len(f.audio) for f in audio_frames), len(quiet(0.3) + speech(0.5)) + int(0.2 * SR) * 2)


if __name__ == "__main__":
    unittest.main()

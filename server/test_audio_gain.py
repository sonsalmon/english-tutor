import unittest

import numpy as np

from server import audio_gain
from server.audio_gain import ChainAudioFilter, InputGainFilter, input_gain_settings

RATE = 16000
FRAME = 320  # 20 ms


def dbfs(x: np.ndarray) -> float:
    return 20 * np.log10(max(float(np.sqrt(np.mean(np.square(x)))), 1e-9))


def to_pcm(x: np.ndarray) -> bytes:
    return np.clip(np.rint(x * 32768), -32768, 32767).astype(np.int16).tobytes()


def sine(seconds: float, rms_dbfs: float) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    return np.sin(2 * np.pi * 220 * t) * 10 ** (rms_dbfs / 20) * np.sqrt(2)


def noise(seconds: float, rms_dbfs: float, seed: int = 0) -> np.ndarray:
    x = np.random.default_rng(seed).standard_normal(int(RATE * seconds))
    return x / np.sqrt(np.mean(x * x)) * 10 ** (rms_dbfs / 20)


async def run(f, x: np.ndarray) -> np.ndarray:
    await f.start(RATE)
    pcm = to_pcm(x)
    out = b"".join([await f.filter(pcm[i:i + FRAME * 2]) for i in range(0, len(pcm), FRAME * 2)])
    return np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768


class InputGainSettingsTest(unittest.TestCase):
    def test_defaults_are_auto(self):
        self.assertEqual(input_gain_settings({}), {"target_dbfs": -20.0, "max_db": 18.0, "gate_dbfs": -50.0})

    def test_off_returns_none(self):
        for value in ("off", "OFF", " off "):
            self.assertIsNone(input_gain_settings({"LIVE_INPUT_GAIN": value}))

    def test_knobs_and_bad_values(self):
        env = {"LIVE_INPUT_GAIN": "auto", "LIVE_INPUT_GAIN_TARGET_DBFS": "-18", "LIVE_INPUT_GAIN_MAX_DB": "99", "LIVE_INPUT_GATE_DBFS": "abc"}
        with self.assertLogs(audio_gain.logger, "WARNING"):
            settings = input_gain_settings(env)
        self.assertEqual(settings, {"target_dbfs": -18.0, "max_db": 18.0, "gate_dbfs": -50.0})
        with self.assertLogs(audio_gain.logger, "WARNING"):
            self.assertIsNotNone(input_gain_settings({"LIVE_INPUT_GAIN": "loud"}))


class InputGainFilterTest(unittest.IsolatedAsyncioTestCase):
    async def test_digital_silence_is_untouched(self):
        f = InputGainFilter()
        await f.start(RATE)
        silence = bytes(FRAME * 2)
        self.assertEqual(await f.filter(silence), silence)

    async def test_quiet_speech_reaches_target(self):
        x = np.concatenate([noise(0.5, -62), sine(1.5, -29)])
        y = await run(InputGainFilter(), x)
        self.assertAlmostEqual(dbfs(y[-RATE:]), -20.0, delta=3.0)
        self.assertLess(np.abs(y).max(), 10 ** (-1 / 20) + 1e-3)

    async def test_loud_speech_is_not_touched(self):
        x = sine(1.0, -15)
        f = InputGainFilter()
        y = await run(f, x)
        np.testing.assert_array_equal(np.frombuffer(to_pcm(x), dtype=np.int16), np.rint(y * 32768).astype(np.int16))
        self.assertEqual(f.gain_db, 0.0)

    async def test_loud_speech_onset_is_not_boosted(self):
        speech = sine(1.0, -15)
        speech[: RATE // 25] *= np.linspace(0.02, 1.0, RATE // 25)
        x = np.concatenate([noise(0.5, -62), speech])
        y = await run(InputGainFilter(), x)
        self.assertAlmostEqual(dbfs(y[RATE // 2:]), dbfs(x[RATE // 2:]), delta=1.5)

    async def test_noise_floor_limits_gain(self):
        x = np.concatenate([noise(1.5, -58), sine(1.5, -45)])
        f = InputGainFilter()
        await run(f, x)
        self.assertLessEqual(f.gain_db, 13.5)  # -45 dBFS - (-58 dBFS) = 13 dB (+ 추적 오차)
        self.assertGreater(f.gain_db, 5.0)

    async def test_gain_never_exceeds_max(self):
        f = InputGainFilter(max_db=6.0)
        await run(f, np.concatenate([noise(0.5, -70), sine(1.0, -40)]))
        self.assertLessEqual(f.gain_db, 6.0 + 1e-6)

    async def test_spikes_are_soft_clipped_below_minus_one_dbfs(self):
        x = noise(1.5, -36, seed=3)
        x[::97] = 0.8
        y = await run(InputGainFilter(), x)
        self.assertGreater(np.abs(y).max(), 0.6)
        self.assertLess(np.abs(y).max(), 10 ** (-1 / 20) + 1e-3)


class RecordingFilter(audio_gain.BaseAudioFilter):
    def __init__(self, name, log):
        self.name, self.log = name, log

    async def start(self, sample_rate):
        self.log.append(("start", self.name, sample_rate))

    async def stop(self):
        self.log.append(("stop", self.name))

    async def process_frame(self, frame):
        self.log.append(("frame", self.name, frame))

    async def filter(self, audio):
        self.log.append(("filter", self.name))
        return audio + self.name.encode()


class ChainAudioFilterTest(unittest.IsolatedAsyncioTestCase):
    async def test_chain_runs_filters_in_order_and_fans_out(self):
        log = []
        chain = ChainAudioFilter([RecordingFilter("a", log), RecordingFilter("b", log)])
        await chain.start(16000)
        self.assertEqual(await chain.filter(b""), b"ab")
        await chain.process_frame("f")
        await chain.stop()
        self.assertEqual(
            log,
            [("start", "a", 16000), ("start", "b", 16000), ("filter", "a"), ("filter", "b"),
             ("frame", "a", "f"), ("frame", "b", "f"), ("stop", "a"), ("stop", "b")],
        )


if __name__ == "__main__":
    unittest.main()

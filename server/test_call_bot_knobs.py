import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import barge_in, call_bot
from server.audio_gain import ChainAudioFilter, InputGainFilter
from server.call_bot import CallRecord

ALL_OFF = {"LIVE_BARGE_IN_MODE": "words", "LIVE_INPUT_GAIN": "off", "LIVE_SILENCE_REENGAGE_SEC": "0"}


class BargeInEnvTest(unittest.TestCase):
    def test_mode_defaults_to_vad_and_parses_three_values(self):
        self.assertEqual(call_bot.barge_in_mode_from_env({}), "vad")
        for value in ("vad", "words", "native"):
            self.assertEqual(call_bot.barge_in_mode_from_env({"LIVE_BARGE_IN_MODE": f" {value.upper()} "}), value)

    def test_bad_mode_warns_and_falls_back(self):
        with mock.patch.object(call_bot.logger, "warning") as warn:
            self.assertEqual(call_bot.barge_in_mode_from_env({"LIVE_BARGE_IN_MODE": "loud"}), "vad")
        warn.assert_called_once()

    def test_gate_settings_defaults_and_overrides(self):
        self.assertEqual(
            call_bot.barge_in_gate_settings({}),
            {"min_voiced_ms": 700, "confidence": 0.7, "min_dbfs": -40.0},
        )
        env = {"LIVE_BARGE_IN_MIN_VOICED_MS": "900", "LIVE_BARGE_IN_CONFIDENCE": "0.8", "LIVE_BARGE_IN_MIN_DBFS": "-35"}
        self.assertEqual(call_bot.barge_in_gate_settings(env), {"min_voiced_ms": 900, "confidence": 0.8, "min_dbfs": -35.0})

    def test_gate_settings_ignore_each_bad_knob_separately(self):
        env = {"LIVE_BARGE_IN_MIN_VOICED_MS": "10", "LIVE_BARGE_IN_CONFIDENCE": "x", "LIVE_BARGE_IN_MIN_DBFS": "-30"}
        with mock.patch.object(call_bot.logger, "warning") as warn:
            got = call_bot.barge_in_gate_settings(env)
        self.assertEqual(got, {"min_voiced_ms": 700, "confidence": 0.7, "min_dbfs": -30.0})
        self.assertEqual(warn.call_count, 2)


class ProactiveAudioEnvTest(unittest.TestCase):
    def test_default_on_off_and_bad_value(self):
        self.assertTrue(call_bot.proactive_audio_from_env({}))
        self.assertTrue(call_bot.proactive_audio_from_env({"LIVE_PROACTIVE_AUDIO": " ON "}))
        self.assertFalse(call_bot.proactive_audio_from_env({"LIVE_PROACTIVE_AUDIO": " Off "}))
        with mock.patch.object(call_bot.logger, "warning") as warn:
            self.assertTrue(call_bot.proactive_audio_from_env({"LIVE_PROACTIVE_AUDIO": "maybe"}))
        warn.assert_called_once()


class SilenceReengageEnvTest(unittest.TestCase):
    def test_defaults_zero_and_bad_values(self):
        self.assertEqual(call_bot.silence_reengage_from_env({}), (10, 2))
        self.assertEqual(call_bot.silence_reengage_from_env({"LIVE_SILENCE_REENGAGE_SEC": "0"}), (0, 2))
        self.assertEqual(call_bot.silence_reengage_from_env({"LIVE_SILENCE_REENGAGE_SEC": "15", "LIVE_SILENCE_REENGAGE_MAX": "1"}), (15, 1))
        with mock.patch.object(call_bot.logger, "warning") as warn:
            self.assertEqual(call_bot.silence_reengage_from_env({"LIVE_SILENCE_REENGAGE_SEC": "-3", "LIVE_SILENCE_REENGAGE_MAX": "z"}), (10, 2))
        self.assertEqual(warn.call_count, 2)

    def test_prompt_carries_the_prefix_and_the_seconds(self):
        text = call_bot.silence_prompt(10)
        self.assertTrue(text.startswith(call_bot.SILENCE_NOTE_PREFIX))
        self.assertIn("10 seconds", text)
        self.assertTrue(text.endswith("]"))

    def test_silence_note_never_becomes_a_learner_turn(self):
        record = CallRecord()
        record.add_user(call_bot.silence_prompt(10))
        record.add_user("  [Silence note: echoed by the model]")
        self.assertEqual(record.chunks, [])
        record.add_user("I was thinking about it")
        self.assertEqual(record.chunks, [("Me", "I was thinking about it")])


class CallKnobsSummaryTest(unittest.TestCase):
    def test_all_switches_off_adds_nothing(self):
        for mode in ("smalltalk", "freetalk", "mission", "teachback"):
            self.assertEqual(call_bot.call_knobs_summary(mode, ALL_OFF), "")

    def test_defaults_list_active_knobs_and_skip_reengage_outside_chat(self):
        self.assertEqual(call_bot.call_knobs_summary("smalltalk", {}), "barge=vad gain=auto reengage=10s")
        self.assertEqual(call_bot.call_knobs_summary("mission", {}), "barge=vad gain=auto")


class AudioInFilterSwitchTest(unittest.TestCase):
    def setUp(self):
        pyrnnoise = mock.patch.object(call_bot, "build_noise_filter")
        self.noise = pyrnnoise.start()
        self.addCleanup(pyrnnoise.stop)
        self.noise.return_value = object()

    def test_gain_off_is_exactly_the_noise_filter(self):
        got = call_bot.build_audio_in_filter({"LIVE_INPUT_GAIN": "off"})
        self.assertIs(got, self.noise.return_value)

    def test_both_off_is_none(self):
        self.noise.return_value = None
        self.assertIsNone(call_bot.build_audio_in_filter({"LIVE_INPUT_GAIN": "off"}))

    def test_gain_only_when_noise_filter_is_off(self):
        self.noise.return_value = None
        self.assertIsInstance(call_bot.build_audio_in_filter({}), InputGainFilter)

    def test_default_chain_is_gain_then_noise(self):
        got = call_bot.build_audio_in_filter({})
        self.assertIsInstance(got, ChainAudioFilter)
        self.assertIsInstance(got.filters[0], InputGainFilter)
        self.assertIs(got.filters[1], self.noise.return_value)

    def test_gain_knobs_reach_the_filter(self):
        self.noise.return_value = None
        got = call_bot.build_audio_in_filter({"LIVE_INPUT_GAIN_TARGET_DBFS": "-18", "LIVE_INPUT_GAIN_MAX_DB": "12"})
        self.assertEqual((got.target_dbfs, got.max_db), (-18.0, 12.0))


class GateDefaultsTest(unittest.TestCase):
    def test_call_bot_defaults_match_the_gate_module(self):
        self.assertEqual(barge_in.DEFAULT_MIN_VOICED_MS, 700)
        self.assertEqual(call_bot.LEARNER_VOICE_MS, 300)


if __name__ == "__main__":
    unittest.main()

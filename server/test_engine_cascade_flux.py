import asyncio
import logging
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipecat.frames.frames import BotStartedSpeakingFrame, TranscriptionFrame
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
from pipecat.services.google.vertex.llm import GoogleVertexLLMService
from pipecat.turns.user_start.min_words_user_turn_start_strategy import MinWordsUserTurnStartStrategy
from pipecat.turns.user_stop import EagerUserTurnStopStrategy

from server import call_bot
from server.engines import base, cascade_flux

FAKE_KEYS = {"DEEPGRAM_API_KEY": "fake-deepgram-key", "CARTESIA_API_KEY": "fake-cartesia-key"}
INSTRUCTION = "You are Jake, a friend. Talk about your week."


def config(partner="jake", **extra):
    return call_bot.CallConfig(
        system_instruction=INSTRUCTION, mode="smalltalk", partner=partner, engine="cascade_flux", **extra
    )


class FakeEnv:
    def __init__(self, **overrides):
        self.overrides = overrides

    def __enter__(self):
        self.saved = dict(os.environ)
        for name in (*FAKE_KEYS, cascade_flux.LLM_MODEL_ENV):
            os.environ.pop(name, None)
        os.environ.update(self.overrides)

    def __exit__(self, *exc):
        os.environ.clear()
        os.environ.update(self.saved)


def build(partner="jake", **env):
    with FakeEnv(**{**FAKE_KEYS, **env}), mock.patch.object(
        GoogleVertexLLMService, "_get_credentials", return_value=None
    ), mock.patch.object(cascade_flux, "get_project_id", return_value="test-project"):
        return cascade_flux.build_parts(config(partner))


class WiringTest(unittest.TestCase):
    def test_parts_are_flux_vertex_cartesia(self):
        parts = build()

        self.assertIsInstance(parts.stt, DeepgramFluxSTTService)
        self.assertIsInstance(parts.llm, GoogleVertexLLMService)
        self.assertIsInstance(parts.tts, CartesiaTTSService)
        self.assertFalse(parts.realtime_service_mode)

    def test_flux_is_english_with_eager_end_of_turn(self):
        stt = build().stt

        self.assertTrue(stt.eager_end_of_turn_enabled)
        self.assertEqual(stt._settings.model, "flux-general-en")

    def test_llm_keeps_the_request_system_instruction(self):
        llm = build().llm

        self.assertEqual(llm._settings.system_instruction, INSTRUCTION)
        self.assertEqual(llm._settings.model, "gemini-2.5-flash")
        self.assertEqual(llm._project_id, "test-project")

    def test_llm_model_comes_from_the_environment(self):
        parts = build(CASCADE_LLM_MODEL="gemini-3.6-flash")

        self.assertEqual(parts.llm._settings.model, "gemini-3.6-flash")
        self.assertEqual(parts.model_name, "flux+gemini-3.6-flash+sonic-3.6")

    def test_llm_uses_the_server_location(self):
        with mock.patch.dict(os.environ, {"LOCATION": "europe-west4"}):
            llm = build().llm

        self.assertEqual(llm._location, "europe-west4")

    def test_model_name_for_the_transcript(self):
        self.assertEqual(build().model_name, "flux+gemini-2.5-flash+sonic-3.6")

    def test_tts_is_sonic_36_in_english_with_the_partner_voice(self):
        settings = build("priya").tts._settings

        self.assertEqual(settings.model, "sonic-3.6")
        self.assertEqual(settings.voice, cascade_flux.PARTNER_VOICES["priya"])
        self.assertEqual(settings.language, "en")


class MinWordsTest(unittest.TestCase):
    def strategies(self):
        return build().user_params.user_turn_strategies

    def test_start_strategy_is_min_words_3_and_stop_is_eager(self):
        strategies = self.strategies()

        self.assertEqual([type(s) for s in strategies.start], [MinWordsUserTurnStartStrategy])
        self.assertEqual(strategies.start[0]._min_words, 3)
        self.assertEqual([type(s) for s in strategies.stop], [EagerUserTurnStopStrategy])

    def test_backchannel_does_not_interrupt_a_speaking_partner(self):
        strategy = self.strategies().start[0]
        started = mock.AsyncMock()

        async def feed():
            await strategy.process_frame(BotStartedSpeakingFrame())
            for text in ("mm-hm", "yeah", "oh wow"):
                await strategy.process_frame(TranscriptionFrame(text, "user", "2026-10-26T00:00:00Z"))
            self.assertEqual(started.await_count, 0)
            await strategy.process_frame(TranscriptionFrame("wait that is wild", "user", "2026-10-26T00:00:00Z"))

        with mock.patch.object(strategy, "trigger_user_turn_started", started), mock.patch.object(
            strategy, "trigger_reset_aggregation", mock.AsyncMock()
        ):
            asyncio.run(feed())

        started.assert_awaited_once()


class VoiceTableTest(unittest.TestCase):
    def test_friends_have_natural_voices_and_unknown_partners_get_the_default(self):
        self.assertEqual(cascade_flux.voice_for_partner("jake"), cascade_flux.voice_for_partner("brian"))
        self.assertNotEqual(cascade_flux.voice_for_partner("jake"), cascade_flux.voice_for_partner("priya"))
        for partner in (None, "", "park", "omar"):
            self.assertEqual(cascade_flux.voice_for_partner(partner), cascade_flux.DEFAULT_VOICE_ID)

    def test_voice_ids_are_cartesia_uuids(self):
        for voice in (*cascade_flux.PARTNER_VOICES.values(), cascade_flux.DEFAULT_VOICE_ID):
            self.assertRegex(voice, r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class MissingKeyTest(unittest.TestCase):
    def test_reason_names_the_missing_keys_only(self):
        with FakeEnv(DEEPGRAM_API_KEY="fake-deepgram-key"):
            reason = cascade_flux.unavailable_reason()

        self.assertIn("CARTESIA_API_KEY", reason)
        self.assertNotIn("DEEPGRAM_API_KEY", reason)
        self.assertNotIn("fake-deepgram-key", reason)

    def test_blank_key_counts_as_missing(self):
        with FakeEnv(DEEPGRAM_API_KEY="  ", CARTESIA_API_KEY="fake-cartesia-key"):
            self.assertIn("DEEPGRAM_API_KEY", cascade_flux.unavailable_reason())

    def test_no_reason_when_both_keys_exist(self):
        with FakeEnv(**FAKE_KEYS):
            self.assertIsNone(cascade_flux.unavailable_reason())

    def test_build_parts_without_keys_raises_the_reason(self):
        with FakeEnv(), self.assertRaises(RuntimeError) as caught:
            cascade_flux.build_parts(config())

        self.assertIn("DEEPGRAM_API_KEY", str(caught.exception))
        self.assertIn("CARTESIA_API_KEY", str(caught.exception))

    def test_seam_turns_the_missing_key_into_a_400_reason(self):
        request = {"system_instruction": "x", "mode": "smalltalk", "engine": "cascade_flux"}
        with FakeEnv(), self.assertRaises(ValueError) as caught:
            reason = cascade_flux.unavailable_reason()
            call_bot.parse_call_config(request)

        self.assertEqual(str(caught.exception), reason)
        self.assertIn("DEEPGRAM_API_KEY", reason)

    def test_seam_accepts_the_engine_when_keys_exist(self):
        request = {"system_instruction": "x", "mode": "smalltalk", "engine": "cascade_flux"}
        with FakeEnv(**FAKE_KEYS):
            self.assertEqual(call_bot.parse_call_config(request).engine, "cascade_flux")

    def test_registry_points_at_this_module(self):
        self.assertEqual(base.ENGINE_MODULES["cascade_flux"], cascade_flux.__name__)


class SpokenTextTest(unittest.TestCase):
    def test_stage_directions_are_removed(self):
        for raw, expected in (
            ("*laughs* Yeah, totally.", " Yeah, totally."),
            ("Ha (laughs) that is funny.", "Ha  that is funny."),
            ("[laughter] Okay okay.", " Okay okay."),
            ("Right <break time=\"1s\"/> so anyway.", "Right  so anyway."),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(" ".join(cascade_flux.spoken_text(raw).split()), " ".join(expected.split()))

    def test_markdown_and_emoji_are_removed(self):
        self.assertEqual(cascade_flux.spoken_text("**Honestly**, I love it \U0001F600"), "Honestly, I love it ")
        self.assertEqual(cascade_flux.spoken_text("# Title\n- one\n- two"), "Title\none\ntwo")
        self.assertEqual(cascade_flux.spoken_text("use `npm run dev`"), "use npm run dev")

    def test_plain_speech_is_untouched(self):
        for text in ("I'm not sure, honestly.", " and then we left.", "snake_case is fine", "Wait, what?!"):
            with self.subTest(text=text):
                self.assertEqual(cascade_flux.spoken_text(text), text)

    def test_filter_object_applies_the_same_cleaning(self):
        text_filter = cascade_flux.make_spoken_text_filter()

        self.assertEqual(asyncio.run(text_filter.filter("*smiles* Hey.")).strip(), "Hey.")


class TurnTimerTest(unittest.TestCase):
    def test_logs_each_turn_latency_and_ignores_audio_without_a_turn(self):
        now = [10.0]
        timer = cascade_flux.TurnTimer(clock=lambda: now[0])
        self.assertIsNone(timer.first_audio())

        timer.end_of_turn()
        now[0] = 10.85
        with self.assertLogs(cascade_flux.logger, logging.INFO) as logs:
            self.assertAlmostEqual(timer.first_audio(), 850, places=3)
        self.assertIn("Turn latency #1: 850 ms", logs.output[0])
        self.assertIsNone(timer.first_audio())

        timer.end_of_turn()
        now[0] = 12.0
        with self.assertLogs(cascade_flux.logger, logging.INFO) as logs:
            timer.first_audio()
        self.assertIn("Turn latency #2: 1150 ms", logs.output[0])


if __name__ == "__main__":
    unittest.main()

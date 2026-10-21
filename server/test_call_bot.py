import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import call_bot
from server.call_bot import CallConfig, CallRecord, finish_call, mission_title, parse_call_config

INSTRUCTION = 'You are Ms. Park.\nThe user ... trying to: "Day 1 Team Intro" (intro)'

CHAT_DEFAULT_VAD = {"end_sensitivity": call_bot.EndSensitivity.END_SENSITIVITY_HIGH, "silence_duration_ms": 500}


class ParseCallConfigTest(unittest.TestCase):
    def test_valid_mission(self):
        config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "mission"})

        self.assertEqual(config.mission, "Day 1 Team Intro")
        self.assertEqual(config.voice, "Puck")
        self.assertTrue(config.opener)

    def test_teachback_has_no_opener_and_its_own_time_limit(self):
        with mock.patch.dict(os.environ, {"SESSION_TIME_LIMIT": "600", "TEACHBACK_TIME_LIMIT": "900"}):
            config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "teachback"})
            mission = parse_call_config({"system_instruction": INSTRUCTION, "mode": "mission"})

            self.assertFalse(config.opener)
            self.assertEqual(config.time_limit, 900)
            self.assertEqual(mission.time_limit, 600)

    def test_smalltalk_has_opener_and_no_time_limit(self):
        # 친구 통화는 서버 시간 제한이 없다(옵션 환경 변수를 줘도 무시).
        with mock.patch.dict(os.environ, {"SESSION_TIME_LIMIT": "600", "TEACHBACK_TIME_LIMIT": "900", "SMALLTALK_TIME_LIMIT": "420"}):
            config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "smalltalk"})
            mission = parse_call_config({"system_instruction": INSTRUCTION, "mode": "mission"})

            self.assertTrue(config.opener)
            self.assertIsNone(config.time_limit)
            self.assertEqual(mission.time_limit, 600)

    def test_time_limit_by_mode(self):
        env = {"SESSION_TIME_LIMIT": "600", "TEACHBACK_TIME_LIMIT": "900"}
        limits = {mode: call_bot.time_limit_for_mode(mode, env) for mode in call_bot.MODES}

        self.assertEqual(limits, {"mission": 600, "freetalk": 600, "teachback": 900, "smalltalk": None})
        self.assertEqual(call_bot.time_limit_for_mode(None, env), 600)

    def test_pause_limit_defaults_to_600(self):
        env = {k: v for k, v in os.environ.items() if k != "PAUSE_LIMIT_SEC"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(call_bot.pause_limit_from_env(), 600)

    def test_llm_gave_up_matches_the_pipecat_message(self):
        self.assertTrue(call_bot.llm_gave_up("Max consecutive failures (3) reached, treating as fatal error"))
        self.assertFalse(call_bot.llm_gave_up("Connection error (failure 1/3): closed"))
        self.assertFalse(call_bot.llm_gave_up(None))

    def test_smalltalk_mission_name_comes_from_instruction(self):
        config = parse_call_config({"system_instruction": 'You are Ms. Park. trying to: "Small Talk"', "mode": "smalltalk"})

        self.assertEqual(config.mission, "Small Talk")

    def test_rejects_bad_input(self):
        bad = [
            None,
            "text",
            {},
            {"system_instruction": "   "},
            {"system_instruction": INSTRUCTION, "mode": "debug"},
            {"system_instruction": INSTRUCTION, "voice": "Puck; rm"},
            {"system_instruction": "x" * (call_bot.MAX_INSTRUCTION_CHARS + 1)},
        ]
        for data in bad:
            with self.subTest(data=str(data)[:40]):
                with self.assertRaises(ValueError):
                    parse_call_config(data)

    def test_mission_title_missing(self):
        self.assertIsNone(mission_title("no title here"))


class MissionToolsTest(unittest.TestCase):
    def test_teachback_and_smalltalk_get_no_mission_tool(self):
        for mode in ("teachback", "smalltalk"):
            self.assertIsNone(call_bot.mission_tools(CallConfig(system_instruction=INSTRUCTION, mode=mode)))

    def test_mission_and_free_talk_get_complete_mission(self):
        for mode in ("mission", "freetalk"):
            tools = call_bot.mission_tools(CallConfig(system_instruction=INSTRUCTION, mode=mode))
            self.assertEqual([t.name for t in tools.standard_tools], ["complete_mission"])


class FakeTime:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class CallClockTest(unittest.TestCase):
    def setUp(self):
        self.time = FakeTime()
        self.clock = call_bot.CallClock(now=self.time)

    def test_elapsed_is_zero_before_start_and_counts_after(self):
        self.assertEqual(self.clock.elapsed(), 0.0)
        self.clock.start()
        self.time.t += 30

        self.assertEqual(self.clock.elapsed(), 30)

    def test_paused_time_does_not_count(self):
        self.clock.start()
        self.time.t += 20
        self.assertTrue(self.clock.pause())
        self.time.t += 500
        self.assertEqual(self.clock.elapsed(), 20)
        self.assertEqual(self.clock.paused_for(), 500)
        self.assertTrue(self.clock.resume())
        self.time.t += 10

        self.assertEqual(self.clock.elapsed(), 30)
        self.assertEqual(self.clock.paused_total(), 500)
        self.assertEqual(self.clock.paused_for(), 0)

    def test_double_pause_and_resume_without_pause_do_nothing(self):
        self.assertFalse(self.clock.pause())  # 시작 전
        self.clock.start()
        self.assertFalse(self.clock.resume())
        self.assertTrue(self.clock.pause())
        self.time.t += 5
        self.assertFalse(self.clock.pause())

        self.assertEqual(self.clock.paused_for(), 5)

    def test_check_reports_time_limit_with_remaining_wait(self):
        self.clock.start()
        self.time.t += 100
        self.assertEqual(self.clock.check(180, 600), (None, 80))
        self.time.t += 80

        self.assertEqual(self.clock.check(180, 600), ("time_limit", 0.0))

    def test_check_while_paused_waits_for_pause_limit_not_time_limit(self):
        self.clock.start()
        self.time.t += 170
        self.clock.pause()
        self.time.t += 599
        self.assertEqual(self.clock.check(180, 600), (None, 1))
        self.time.t += 1

        self.assertEqual(self.clock.check(180, 600), ("pause_limit", 0.0))

    def test_check_without_time_limit_never_ends_but_still_enforces_pause_limit(self):
        self.clock.start()
        self.time.t += 100000
        self.assertEqual(self.clock.check(None, 600), (None, None))
        self.clock.pause()
        self.time.t += 599
        self.assertEqual(self.clock.check(None, 600), (None, 1))
        self.time.t += 1

        self.assertEqual(self.clock.check(None, 600), ("pause_limit", 0.0))

    def test_resume_gives_back_the_remaining_session_time(self):
        self.clock.start()
        self.time.t += 170
        self.clock.pause()
        self.time.t += 300
        self.clock.resume()

        self.assertEqual(self.clock.check(180, 600), (None, 10))


class CallRecordTest(unittest.TestCase):
    def test_blank_turns_are_skipped(self):
        record = CallRecord()
        record.add_user("  ")
        record.add_partner("")
        record.add_user(" I started my day. ")

        self.assertEqual(record.chunks, [("Me", "I started my day.")])

    def test_gemini_noise_mark_is_removed_from_learner_turn(self):
        record = CallRecord()
        record.add_user("{} hi, I'm S park")
        record.add_user("{ }")

        self.assertEqual(record.chunks, [("Me", "hi, I'm S park")])

    def test_cjk_filler_in_learner_turn_becomes_mm_or_is_stripped(self):
        record = CallRecord()
        record.add_user("嗯")
        record.add_user("嗯 I think so")
        record.add_partner("嗯")

        self.assertEqual(record.chunks, [("Me", "(mm)"), ("Me", "I think so"), ("Partner", "嗯")])

    def test_learner_must_say_three_words_before_mission_can_end(self):
        record = CallRecord(chunks=[("Partner", "Hello there, how are you today?"), ("Me", "Hi")])
        self.assertFalse(record.learner_has_spoken())

        record.add_user("I am fine")

        self.assertTrue(record.learner_has_spoken())

    def test_mic_audio_is_capped(self):
        record = CallRecord()
        with mock.patch.object(call_bot, "MIC_MAX_BYTES", 10):
            record.add_mic(b"\x01" * 8)
            record.add_mic(b"\x02" * 8)

        self.assertEqual(bytes(record.mic_pcm), b"\x01" * 8 + b"\x02" * 2)


class LiveKnobsTest(unittest.TestCase):
    def test_model_defaults_to_model_env_or_builtin(self):
        self.assertEqual(call_bot.live_model_for("smalltalk", {}), call_bot.DEFAULT_LIVE_MODEL)
        self.assertEqual(call_bot.live_model_for("mission", {"MODEL": "m-base"}), "m-base")
        self.assertEqual(call_bot.live_model_for("freetalk", {"MODEL": "m-base"}), "m-base")

    def test_chat_model_only_for_smalltalk_and_freetalk(self):
        env = {"MODEL": "m-base", "LIVE_MODEL_CHAT": "chat-m", "LIVE_MODEL": "other-m"}
        self.assertEqual(call_bot.live_model_for("smalltalk", env), "chat-m")
        self.assertEqual(call_bot.live_model_for("freetalk", env), "chat-m")
        self.assertEqual(call_bot.live_model_for("mission", env), "other-m")
        self.assertEqual(call_bot.live_model_for("teachback", env), "other-m")

    def test_live_model_alone_does_not_touch_chat(self):
        env = {"MODEL": "m-base", "LIVE_MODEL": "other-m"}
        self.assertEqual(call_bot.live_model_for("smalltalk", env), "m-base")
        self.assertEqual(call_bot.live_model_for("mission", env), "other-m")

    def test_vad_overrides_parse_and_only_for_chat_modes(self):
        env = {"LIVE_VAD_CHAT_END_SENSITIVITY": "high", "LIVE_VAD_CHAT_SILENCE_MS": "800", "LIVE_VAD_CHAT_PREFIX_MS": "150"}
        got = call_bot.chat_vad_overrides("smalltalk", env)
        self.assertEqual(got, {
            "end_sensitivity": call_bot.EndSensitivity.END_SENSITIVITY_HIGH,
            "silence_duration_ms": 800,
            "prefix_padding_ms": 150,
        })
        self.assertEqual(call_bot.chat_vad_overrides("freetalk", env), got)  # 환경 변수는 두 채팅 모드 모두에 적용
        self.assertEqual(call_bot.chat_vad_overrides("mission", env), {})
        self.assertEqual(call_bot.chat_vad_overrides("teachback", env), {})
        self.assertEqual(call_bot.chat_vad_overrides("smalltalk", {}), CHAT_DEFAULT_VAD)
        self.assertEqual(call_bot.chat_vad_overrides("freetalk", {}), {})  # 새 기본값은 smalltalk만

    def test_prefix_ms_has_upper_bound(self):
        self.assertEqual(call_bot.chat_vad_overrides("smalltalk", {"LIVE_VAD_CHAT_PREFIX_MS": "2000"})["prefix_padding_ms"], 2000)
        self.assertEqual(call_bot.chat_vad_overrides("smalltalk", {"LIVE_VAD_CHAT_PREFIX_MS": "2001"}), CHAT_DEFAULT_VAD)
        self.assertEqual(call_bot.chat_vad_overrides("smalltalk", {"LIVE_VAD_CHAT_PREFIX_MS": "999999"}), CHAT_DEFAULT_VAD)

    def test_invalid_vad_values_are_ignored_per_knob(self):
        env = {"LIVE_VAD_CHAT_END_SENSITIVITY": "MID", "LIVE_VAD_CHAT_SILENCE_MS": "50", "LIVE_VAD_CHAT_PREFIX_MS": "abc"}
        self.assertEqual(call_bot.chat_vad_overrides("smalltalk", env), CHAT_DEFAULT_VAD)
        env = {"LIVE_VAD_CHAT_SILENCE_MS": "3001", "LIVE_VAD_CHAT_PREFIX_MS": "-1", "LIVE_VAD_CHAT_END_SENSITIVITY": "LOW"}
        self.assertEqual(call_bot.chat_vad_overrides("smalltalk", env), {**CHAT_DEFAULT_VAD, "end_sensitivity": call_bot.EndSensitivity.END_SENSITIVITY_LOW})
        self.assertEqual(call_bot.chat_vad_overrides("smalltalk", {"LIVE_VAD_CHAT_SILENCE_MS": "100"}), {**CHAT_DEFAULT_VAD, "silence_duration_ms": 100})
        self.assertEqual(call_bot.chat_vad_overrides("smalltalk", {"LIVE_VAD_CHAT_SILENCE_MS": "3000"}), {**CHAT_DEFAULT_VAD, "silence_duration_ms": 3000})

    def test_chat_modes_default_to_high_end_and_500ms_without_env(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIVE_VAD_") and k != "TURN_MODE"}
        with mock.patch.dict(os.environ, env, clear=True):
            chat, _ = call_bot.turn_settings("smalltalk")
            free, _ = call_bot.turn_settings("freetalk")
            mission, _ = call_bot.turn_settings("mission")
            teachback, _ = call_bot.turn_settings("teachback")
        self.assertEqual((chat.silence_duration_ms, chat.end_sensitivity, chat.prefix_padding_ms), (500, call_bot.EndSensitivity.END_SENSITIVITY_HIGH, 500))
        for params in (free, mission, teachback):
            self.assertEqual((params.silence_duration_ms, params.end_sensitivity), (1200, call_bot.EndSensitivity.END_SENSITIVITY_LOW))
        for params in (chat, free, mission, teachback):
            self.assertEqual((params.start_sensitivity, params.prefix_padding_ms), (call_bot.StartSensitivity.START_SENSITIVITY_LOW, 500))
        self.assertEqual(call_bot.vad_summary(call_bot.chat_vad_overrides("smalltalk", {})), "end=HIGH silence_ms=500")

    def test_live_config_for_per_mode(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIVE_") and k not in ("TURN_MODE", "MODEL")}
        low = call_bot.EndSensitivity.END_SENSITIVITY_LOW
        high = call_bot.EndSensitivity.END_SENSITIVITY_HIGH
        with mock.patch.dict(os.environ, env, clear=True):
            got = {m: call_bot.live_config_for(m) for m in ("smalltalk", "freetalk", "mission", "teachback")}
            self.assertEqual(got["smalltalk"][1:2] and (got["smalltalk"][1].silence_duration_ms, got["smalltalk"][1].end_sensitivity), (500, high))
            self.assertEqual(got["smalltalk"][3], "end=HIGH silence_ms=500")
            for mode in ("freetalk", "mission", "teachback"):
                model, vad, user_params, meta = got[mode]
                self.assertEqual((vad.silence_duration_ms, vad.end_sensitivity), (1200, low), mode)
                self.assertIsNone(meta, mode)
                self.assertIsNone(user_params)
            for mode in got:
                self.assertEqual(got[mode][0], call_bot.DEFAULT_LIVE_MODEL)
        with mock.patch.dict(os.environ, {**env, "LIVE_VAD_CHAT_SILENCE_MS": "800"}, clear=True):
            model, vad, _, meta = call_bot.live_config_for("freetalk")
            self.assertEqual((vad.silence_duration_ms, vad.end_sensitivity, meta), (800, low, "silence_ms=800"))
            self.assertEqual(call_bot.live_config_for("mission")[1].silence_duration_ms, 1200)
        self.assertEqual(call_bot.live_config_for("mission", {"LIVE_MODEL": "x"})[0], "x")

    def test_smart_turn_mode_skips_gemini_vad_knobs(self):
        env = {"TURN_MODE": "smart", "LIVE_VAD_CHAT_SILENCE_MS": "800"}
        self.assertEqual(call_bot.chat_vad_overrides("smalltalk", env), {})

    def test_turn_settings_applies_overrides_to_chat_only(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIVE_VAD_") and k != "TURN_MODE"}
        env.update({"LIVE_VAD_CHAT_END_SENSITIVITY": "HIGH", "LIVE_VAD_CHAT_SILENCE_MS": "700"})
        with mock.patch.dict(os.environ, env, clear=True):
            chat, _ = call_bot.turn_settings("smalltalk")
            mission, _ = call_bot.turn_settings("mission")
            teachback, _ = call_bot.turn_settings("teachback")
            plain, _ = call_bot.turn_settings()

        self.assertEqual((chat.silence_duration_ms, chat.end_sensitivity), (700, call_bot.EndSensitivity.END_SENSITIVITY_HIGH))
        self.assertEqual(chat.prefix_padding_ms, 500)  # 설정 안 한 노브는 새 기본값
        for params in (mission, teachback, plain):
            self.assertEqual((params.silence_duration_ms, params.end_sensitivity), (1200, call_bot.EndSensitivity.END_SENSITIVITY_LOW))

    def test_live_config_for_uses_the_given_env_not_the_process_env(self):
        with mock.patch.dict(os.environ, {"LIVE_VAD_PREFIX_MS": "900", "LIVE_VAD_START_SENSITIVITY": "HIGH"}):
            vad = call_bot.live_config_for("mission", {})[1]
            self.assertEqual((vad.start_sensitivity, vad.prefix_padding_ms), (call_bot.StartSensitivity.START_SENSITIVITY_LOW, 500))
            vad = call_bot.live_config_for("mission", {"LIVE_VAD_PREFIX_MS": "700"})[1]
            self.assertEqual(vad.prefix_padding_ms, 700)

    def test_start_vad_defaults_low_and_500ms(self):
        got = call_bot.start_vad_settings({})
        self.assertEqual(got, {"start_sensitivity": call_bot.StartSensitivity.START_SENSITIVITY_LOW, "prefix_padding_ms": 500})

    def test_start_vad_env_overrides_and_invalid_ignored(self):
        got = call_bot.start_vad_settings({"LIVE_VAD_START_SENSITIVITY": "high", "LIVE_VAD_PREFIX_MS": "300"})
        self.assertEqual(got, {"start_sensitivity": call_bot.StartSensitivity.START_SENSITIVITY_HIGH, "prefix_padding_ms": 300})
        for prefix in ("0", "2000"):
            self.assertEqual(call_bot.start_vad_settings({"LIVE_VAD_PREFIX_MS": prefix})["prefix_padding_ms"], int(prefix))
        default = call_bot.start_vad_settings({})
        for env in (
            {"LIVE_VAD_START_SENSITIVITY": "MID"},
            {"LIVE_VAD_PREFIX_MS": "2001"},
            {"LIVE_VAD_PREFIX_MS": "-1"},
            {"LIVE_VAD_PREFIX_MS": "abc"},
        ):
            with mock.patch.object(call_bot.logger, "warning") as warn:
                self.assertEqual(call_bot.start_vad_settings(env), default, env)
            warn.assert_called_once()

    def test_start_vad_env_applies_to_every_mode_and_chat_prefix_wins(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith("LIVE_VAD_") and k != "TURN_MODE"}
        env.update({"LIVE_VAD_START_SENSITIVITY": "HIGH", "LIVE_VAD_PREFIX_MS": "700"})
        with mock.patch.dict(os.environ, env, clear=True):
            for mode in ("smalltalk", "freetalk", "mission", "teachback"):
                params, _ = call_bot.turn_settings(mode)
                self.assertEqual((params.start_sensitivity, params.prefix_padding_ms), (call_bot.StartSensitivity.START_SENSITIVITY_HIGH, 700), mode)
        env["LIVE_VAD_CHAT_PREFIX_MS"] = "150"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(call_bot.turn_settings("smalltalk")[0].prefix_padding_ms, 150)
            self.assertEqual(call_bot.turn_settings("mission")[0].prefix_padding_ms, 700)

    def test_noise_filter_on_by_default_and_off_switch(self):
        for value in ("off", "OFF", "0", "false", "no"):
            self.assertFalse(call_bot.noise_filter_enabled({"NOISE_FILTER": value}))
        for env in ({}, {"NOISE_FILTER": "on"}, {"NOISE_FILTER": ""}):
            self.assertTrue(call_bot.noise_filter_enabled(env))
        self.assertIsNone(call_bot.build_audio_in_filter({"NOISE_FILTER": "off"}))

    def test_noise_filter_built_when_pyrnnoise_present(self):
        from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter

        with mock.patch.object(call_bot.logger, "info") as info:
            self.assertIsInstance(call_bot.build_audio_in_filter({}), RNNoiseFilter)
        info.assert_called_once()
        self.assertIn("Noise filter on", info.call_args.args[0])

    def test_noise_filter_missing_pyrnnoise_warns_and_returns_none(self):
        with mock.patch.dict(sys.modules, {"pyrnnoise": None}), mock.patch.object(call_bot.logger, "warning") as warn:
            self.assertIsNone(call_bot.build_audio_in_filter({}))
        warn.assert_called_once()

    def test_affective_dialog_defaults_on_and_can_be_turned_off(self):
        self.assertTrue(call_bot.affective_dialog_from_env({}))
        self.assertTrue(call_bot.affective_dialog_from_env({"LIVE_AFFECTIVE_DIALOG": "1"}))
        for off in ("0", "false", "OFF", "no"):
            self.assertFalse(call_bot.affective_dialog_from_env({"LIVE_AFFECTIVE_DIALOG": off}))

    def test_vad_summary(self):
        self.assertIsNone(call_bot.vad_summary({}))
        got = call_bot.vad_summary({"end_sensitivity": call_bot.EndSensitivity.END_SENSITIVITY_HIGH, "silence_duration_ms": 800})
        self.assertEqual(got, "end=HIGH silence_ms=800")

    def test_vad_line_lands_in_saved_transcript_below_model(self):
        record = CallRecord(started_at=1_792_450_000.0, chunks=[("Me", "Hi"), ("Partner", "Hello")])
        config = CallConfig(system_instruction=INSTRUCTION, mode="smalltalk")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(call_bot, "get_transcript_dir", return_value=Path(tmp)):
            path = finish_call(record, config, "gemini-3.8-live", ended_at=1_792_450_030.0, vad="end=HIGH silence_ms=800")
            lines = path.read_text(encoding="utf-8").split("\n")
            no_vad = finish_call(CallRecord(started_at=1_792_450_100.0, chunks=[("Me", "Hi")]), config, "m", ended_at=1_792_450_130.0)

            idx = lines.index("- model: gemini-3.8-live")
            self.assertEqual(lines[idx + 1], "- vad: end=HIGH silence_ms=800")
            self.assertNotIn("- vad:", no_vad.read_text(encoding="utf-8"))


class FinishCallTest(unittest.TestCase):
    def test_audio_is_saved_before_transcript_with_mission_metadata(self):
        order = []
        record = CallRecord(started_at=1_792_450_000.0, chunks=[("Me", "Hi")], mic_pcm=bytearray(b"\x00\x01"), completed=True)
        config = CallConfig(system_instruction=INSTRUCTION, mode="mission")

        with mock.patch.object(call_bot, "save_call_audio", side_effect=lambda *a, **k: order.append("wav")), \
                mock.patch.object(call_bot, "save_transcript", side_effect=lambda chunks, meta, d: order.append(("md", meta))), \
                mock.patch.object(call_bot, "get_transcript_dir", return_value=Path("/tmp")):
            finish_call(record, config, "model-x", ended_at=1_792_450_065.0)

        self.assertEqual(order[0], "wav")
        meta = order[1][1]
        self.assertEqual((meta["mission"], meta["completed"], meta["duration_sec"], meta["model"]), ("Day 1 Team Intro", True, 65, "model-x"))

    def test_paused_seconds_are_not_part_of_the_duration(self):
        record = CallRecord(started_at=1_792_450_000.0, chunks=[("Me", "Hi")], paused_sec=40.0)
        config = CallConfig(system_instruction=INSTRUCTION, mode="smalltalk")

        with mock.patch.object(call_bot, "save_transcript", side_effect=lambda chunks, meta, d: meta) as save_md, \
                mock.patch.object(call_bot, "get_transcript_dir", return_value=Path("/tmp")):
            meta = finish_call(record, config, "m", ended_at=1_792_450_100.0)

        self.assertEqual(meta["duration_sec"], 60)
        self.assertEqual(meta["voice"], config.voice)
        save_md.assert_called_once()

    def test_audio_failure_does_not_block_transcript(self):
        record = CallRecord(chunks=[("Me", "Hi")], mic_pcm=bytearray(b"\x00"))
        config = CallConfig(system_instruction=INSTRUCTION, mode="mission")

        with mock.patch.object(call_bot, "save_call_audio", side_effect=OSError("disk")), \
                mock.patch.object(call_bot, "save_transcript", return_value=Path("/tmp/x.md")) as save_md, \
                mock.patch.object(call_bot, "get_transcript_dir", return_value=Path("/tmp")):
            self.assertEqual(finish_call(record, config, "m"), Path("/tmp/x.md"))

        save_md.assert_called_once()


class UsageMetricsTest(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def metrics_frame(prompt, completion, input_audio, output_audio):
        from pipecat.frames.frames import MetricsFrame
        from pipecat.metrics.metrics import LLMTokenUsage, LLMUsageMetricsData, TTFBMetricsData

        tokens = LLMTokenUsage(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            input_audio_tokens=input_audio,
            output_audio_tokens=output_audio,
        )
        return MetricsFrame(data=[TTFBMetricsData(processor="llm", value=0.4), LLMUsageMetricsData(processor="llm", value=tokens)])

    def test_only_token_usage_is_summed_split_into_audio_and_text(self):
        record = CallRecord()
        for frame in (self.metrics_frame(1000, 200, 800, 150), self.metrics_frame(2000, 100, None, None)):
            call_bot.add_usage_metrics(record.usage, frame.data)

        self.assertEqual(
            (record.usage.input_text, record.usage.input_audio, record.usage.output_text, record.usage.output_audio),
            (200 + 2000, 800, 50 + 100, 150),
        )

    async def test_collector_sums_metrics_frames_and_passes_every_frame_on(self):
        from pipecat.frames.frames import MetricsFrame
        from pipecat.tests.utils import run_test

        record = CallRecord()
        down, _up = await run_test(
            call_bot.make_usage_collector(record.usage),
            frames_to_send=[self.metrics_frame(1000, 200, 800, 150), self.metrics_frame(500, 20, 400, 10)],
        )

        self.assertEqual([type(f) for f in down], [MetricsFrame, MetricsFrame])
        self.assertEqual((record.usage.input_audio, record.usage.output_audio), (1200, 160))

    def test_finish_call_puts_estimated_cost_in_meta_and_none_without_usage(self):
        config = CallConfig(system_instruction=INSTRUCTION, mode="mission")
        record = CallRecord(chunks=[("Me", "Hi")])
        record.usage.add_tokens(1_000_000, 100_000, 1_000_000, 100_000)

        with mock.patch.object(call_bot, "save_transcript", side_effect=lambda chunks, meta, d: meta), \
                mock.patch.object(call_bot, "get_transcript_dir", return_value=Path("/tmp")):
            meta = finish_call(record, config, "gemini-live-2.5-flash-native-audio")
            no_usage = finish_call(CallRecord(chunks=[("Me", "Hi")]), config, "gemini-live-2.5-flash-native-audio")
            unknown = finish_call(record, config, "some-other-model")

        self.assertEqual(meta["cost_usd"], 4.2)
        self.assertIsNone(no_usage["cost_usd"])
        self.assertIsNone(unknown["cost_usd"])


class FakeRequest:
    def __init__(self, body, content_type="application/json"):
        self._body = body
        self.headers = {"content-type": content_type}

    async def json(self):
        return self._body


class OfferEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_config_is_rejected_before_connecting(self):
        from fastapi import BackgroundTasks, HTTPException

        from server import main

        with mock.patch.object(main._webrtc, "handle_web_request") as handle:
            with self.assertRaises(HTTPException) as ctx:
                await main.offer(FakeRequest({"sdp": "v=0", "type": "offer", "requestData": {"mode": "mission"}}), BackgroundTasks())

        self.assertEqual(ctx.exception.status_code, 400)
        handle.assert_not_called()

    async def test_non_json_offer_from_other_pages_is_refused(self):
        from fastapi import BackgroundTasks, HTTPException

        from server import main

        body = {"sdp": "v=0", "type": "offer", "requestData": {"system_instruction": INSTRUCTION}}
        with mock.patch.object(main._webrtc, "handle_web_request") as handle:
            with self.assertRaises(HTTPException) as ctx:
                await main.offer(FakeRequest(body, content_type="text/plain"), BackgroundTasks())

        self.assertEqual(ctx.exception.status_code, 415)
        handle.assert_not_called()

    async def test_browser_camel_case_request_data_starts_the_bot(self):
        from fastapi import BackgroundTasks

        from server import main

        tasks = BackgroundTasks()

        async def fake_handle(request, webrtc_connection_callback):
            await webrtc_connection_callback("connection")
            return {"sdp": "answer", "type": "answer", "pc_id": "pc-1"}

        with mock.patch.object(main._webrtc, "handle_web_request", side_effect=fake_handle):
            answer = await main.offer(
                FakeRequest({"sdp": "v=0", "type": "offer", "requestData": {"system_instruction": INSTRUCTION, "mode": "freetalk"}}),
                tasks,
            )

        self.assertEqual(answer["pc_id"], "pc-1")
        self.assertEqual(len(tasks.tasks), 1)
        config = tasks.tasks[0].args[1]
        self.assertEqual((config.mode, config.mission), ("freetalk", "Day 1 Team Intro"))


class PartnerConfigTest(unittest.TestCase):
    def parse(self, **extra):
        return parse_call_config({"system_instruction": INSTRUCTION, "mode": "smalltalk", **extra})

    def test_seven_ids_are_kept(self):
        for pid in ("priya", "omar", "lukas", "carmen", "jake", "chloe", "brian"):
            self.assertEqual(self.parse(partner=pid).partner, pid)

    def test_other_values_mean_ms_park(self):
        for value in (None, "park", "Priya", "x", 3, ["priya"]):
            self.assertIsNone(self.parse(partner=value).partner)
        self.assertIsNone(self.parse().partner)

    def test_teachback_never_has_a_partner(self):
        config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "teachback", "partner": "omar"})

        self.assertIsNone(config.partner)

    def test_brian_is_accepted_for_smalltalk_and_freetalk_only(self):
        for mode, expected in (("smalltalk", "brian"), ("freetalk", "brian"), ("mission", None), ("teachback", None)):
            with self.subTest(mode=mode):
                config = parse_call_config({"system_instruction": INSTRUCTION, "mode": mode, "partner": "brian"})
                self.assertEqual(config.partner, expected)

    def test_only_smalltalk_and_freetalk_keep_a_partner(self):
        for mode, expected in (("smalltalk", "omar"), ("freetalk", "omar"), ("mission", None), ("teachback", None)):
            with self.subTest(mode=mode):
                config = parse_call_config({"system_instruction": INSTRUCTION, "mode": mode, "partner": "omar"})
                self.assertEqual(config.partner, expected)

    def test_opener_text_uses_the_partner_name(self):
        names = {"priya": "Priya", "omar": "Omar", "lukas": "Lukas", "carmen": "Carmen", "jake": "Jake", "chloe": "Chloe", "brian": "Brian"}
        for pid, name in names.items():
            self.assertEqual(call_bot.opener_text(pid), f"[The learner just joined the call. Start as {name}.]")
        for value in (None, "park"):
            self.assertEqual(call_bot.opener_text(value), call_bot.OPENER_TEXT)
        self.assertIn("Ms. Park", call_bot.OPENER_TEXT)

    def test_partner_reaches_the_saved_transcript(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TRANSCRIPT_DIR": tmp, "AUDIO_DIR": tmp}):
            record = CallRecord()
            record.add_user("hello there my friend")
            path = finish_call(record, self.parse(partner="jake"), "m")

            self.assertIn("- partner: jake\n", path.read_text(encoding="utf-8"))


class PartnerMemorySchedulingTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        call_bot._PARTNER_UPDATED.clear()
        patcher = mock.patch.object(call_bot, "update_partner_memory_sync", return_value=True)
        self.update = patcher.start()
        self.addCleanup(patcher.stop)

    def config(self, mode="smalltalk", partner="priya"):
        return parse_call_config({"system_instruction": INSTRUCTION, "mode": mode, "partner": partner})

    def record(self, *chunks):
        return CallRecord(chunks=list(chunks))

    async def run_task(self, task):
        if task is not None:
            await task

    async def test_partner_call_schedules_exactly_one_update_with_its_turns(self):
        record = self.record(("Me", "I like jazz"), ("Partner", "Nice!"))
        saved = Path("/tmp/2026-10-20-100000.md")

        first = call_bot.schedule_partner_memory_update(saved, self.config(), record)
        second = call_bot.schedule_partner_memory_update(saved, self.config(), record)
        await self.run_task(first)

        self.assertIsNone(second)
        self.update.assert_called_once_with("priya", [("Me", "I like jazz"), ("Partner", "Nice!")])

    async def test_no_update_for_ms_park_mission_or_no_learner_line(self):
        saved = Path("/tmp/a.md")
        talk = self.record(("Me", "hello"))
        cases = (
            (saved, self.config(partner=None), talk),
            (saved, self.config(mode="mission"), talk),
            (saved, self.config(), self.record(("Partner", "hi"))),
            (saved, self.config(), self.record(("Me", "  "))),
            (None, self.config(), talk),
        )
        for case in cases:
            self.assertIsNone(call_bot.schedule_partner_memory_update(*case))
        self.update.assert_not_called()

    async def test_failed_update_can_be_retried(self):
        record = self.record(("Me", "I like jazz"))
        saved = Path("/tmp/b.md")
        self.update.return_value = False
        await self.run_task(call_bot.schedule_partner_memory_update(saved, self.config(), record))
        self.update.return_value = True
        await self.run_task(call_bot.schedule_partner_memory_update(saved, self.config(), record))
        third = call_bot.schedule_partner_memory_update(saved, self.config(), record)

        self.assertEqual(self.update.call_count, 2)
        self.assertIsNone(third)


if __name__ == "__main__":
    unittest.main()

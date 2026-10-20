import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import call_bot
from server.call_bot import CallConfig, CallRecord, finish_call, mission_title, parse_call_config

INSTRUCTION = 'You are Ms. Park.\nThe user ... trying to: "Day 1 Team Intro" (intro)'


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

    def test_smalltalk_has_opener_and_its_own_time_limit(self):
        with mock.patch.dict(os.environ, {"SESSION_TIME_LIMIT": "600", "TEACHBACK_TIME_LIMIT": "900", "SMALLTALK_TIME_LIMIT": "420"}):
            config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "smalltalk"})
            mission = parse_call_config({"system_instruction": INSTRUCTION, "mode": "mission"})

            self.assertTrue(config.opener)
            self.assertEqual(config.time_limit, 420)
            self.assertEqual(mission.time_limit, 600)

    def test_smalltalk_time_limit_defaults_to_300(self):
        env = {k: v for k, v in os.environ.items() if k != "SMALLTALK_TIME_LIMIT"}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(call_bot.smalltalk_time_limit_from_env(), 300)
            self.assertEqual(call_bot.pause_limit_from_env(), 600)

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
        save_md.assert_called_once()

    def test_audio_failure_does_not_block_transcript(self):
        record = CallRecord(chunks=[("Me", "Hi")], mic_pcm=bytearray(b"\x00"))
        config = CallConfig(system_instruction=INSTRUCTION, mode="mission")

        with mock.patch.object(call_bot, "save_call_audio", side_effect=OSError("disk")), \
                mock.patch.object(call_bot, "save_transcript", return_value=Path("/tmp/x.md")) as save_md, \
                mock.patch.object(call_bot, "get_transcript_dir", return_value=Path("/tmp")):
            self.assertEqual(finish_call(record, config, "m"), Path("/tmp/x.md"))

        save_md.assert_called_once()


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


if __name__ == "__main__":
    unittest.main()

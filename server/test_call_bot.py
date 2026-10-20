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

    def test_audio_failure_does_not_block_transcript(self):
        record = CallRecord(chunks=[("Me", "Hi")], mic_pcm=bytearray(b"\x00"))
        config = CallConfig(system_instruction=INSTRUCTION, mode="mission")

        with mock.patch.object(call_bot, "save_call_audio", side_effect=OSError("disk")), \
                mock.patch.object(call_bot, "save_transcript", return_value=Path("/tmp/x.md")) as save_md, \
                mock.patch.object(call_bot, "get_transcript_dir", return_value=Path("/tmp")):
            self.assertEqual(finish_call(record, config, "m"), Path("/tmp/x.md"))

        save_md.assert_called_once()


class FakeRequest:
    def __init__(self, body):
        self._body = body

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

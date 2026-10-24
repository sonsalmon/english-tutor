import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import resume
from server.call_bot import parse_call_config

NOW = 1_800_000_000.0
INSTRUCTION = 'You are Priya.\nThe user is trying to: "Small Talk" (a chat).\nOPENING. Greet the learner.'


def transcript(partner, mission="Small Talk", turns=()):
    head = ["# Call 2026-10-24 21:50", f"- mission: {mission}", "- model: gemini", "- voice: Leda"]
    if partner:
        head.append(f"- partner: {partner}")
    head += ["- duration: 2m 17s", "- completed: no", "- coach: 0", ""]
    body = [f"**{who}:** {text}" for who, text in turns]
    return "\n".join(head + body) + "\n"


def turns(count):
    out = []
    for i in range(count):
        out.append(("Partner" if i % 2 == 0 else "Me", f"line {i}"))
    return out


class ResumeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def save(self, stem, partner, ended_ago, mission="Small Talk", chunks=None):
        path = self.dir / f"{stem}.md"
        path.write_text(transcript(partner, mission, chunks if chunks is not None else turns(20)), encoding="utf-8")
        os.utime(path, (NOW - ended_ago, NOW - ended_ago))
        return path

    def config(self, partner="priya", mode="smalltalk"):
        return parse_call_config({"system_instruction": INSTRUCTION, "mode": mode, "partner": partner})

    def run_resume(self, config):
        return resume.with_resume(config, now=NOW, directory=self.dir)

    def test_call_within_ten_minutes_gets_the_last_twelve_turns(self):
        self.save("2026-10-24-215011", "priya", ended_ago=90)

        out = self.run_resume(self.config())

        self.assertTrue(out.system_instruction.startswith(INSTRUCTION))
        self.assertIn("RESUME OF A CUT-OFF CALL", out.system_instruction)
        self.assertIn("you were cut off", out.system_instruction)
        self.assertIn("about 2 minute(s) ago", out.system_instruction)
        block = out.system_instruction.split("<<<\n")[1].split("\n>>>")[0]
        self.assertEqual(len(block.splitlines()), 12)
        self.assertTrue(block.startswith("Priya: line 8"))
        self.assertTrue(block.endswith("Learner: line 19"))

    def test_auto_redial_uses_the_turns_the_screen_sent_even_before_the_transcript_exists(self):
        sent = [{"who": "partner", "text": "So how was work?"}, {"who": "me", "text": "I  started a new\njob as a server."}]
        config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "smalltalk", "partner": "priya", "resume_turns": sent})

        out = self.run_resume(config)

        block = out.system_instruction.split("<<<\n")[1].split("\n>>>")[0]
        self.assertEqual(block, "Priya: So how was work?\nLearner: I started a new job as a server.")
        self.assertIn("about 1 minute(s) ago", out.system_instruction)

    def test_screen_turns_without_learner_speech_or_with_bad_shapes_fall_back_to_the_transcript(self):
        self.save("2026-10-24-215011", "priya", ended_ago=90)
        sent = [{"who": "partner", "text": "Hey!"}, "junk", {"who": "me", "text": 5}, {"who": "me", "text": "   "}]
        config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "smalltalk", "partner": "priya", "resume_turns": sent})

        self.assertEqual(config.resume_turns, (("Partner", "Hey!"),))
        self.assertIn("Learner: line 19", self.run_resume(config).system_instruction)

    def test_screen_turns_keep_only_the_last_twelve(self):
        sent = [{"who": "me" if i % 2 else "partner", "text": f"t{i}"} for i in range(30)]
        config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "smalltalk", "partner": "priya", "resume_turns": sent})

        self.assertEqual(len(config.resume_turns), 12)
        self.assertEqual(config.resume_turns[-1], ("Me", "t29"))

    def test_friend_mission_ignores_screen_turns(self):
        sent = [{"who": "me", "text": "hi"}]
        config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "mission", "partner": "priya", "resume_turns": sent})

        self.assertEqual(self.run_resume(config), config)

    def test_nothing_is_added_after_ten_minutes_or_without_a_previous_call(self):
        self.assertEqual(self.run_resume(self.config()), self.config())
        self.save("2026-10-24-215011", "priya", ended_ago=resume.RESUME_WINDOW_SEC + 1)

        self.assertEqual(self.run_resume(self.config()).system_instruction, INSTRUCTION)

    def test_only_the_same_friend_counts(self):
        self.save("2026-10-24-215011", "jake", ended_ago=60)
        self.save("2026-10-24-215100", None, ended_ago=30, mission="Free Talk: jobs")

        self.assertEqual(self.run_resume(self.config()).system_instruction, INSTRUCTION)

    def test_latest_call_of_that_friend_is_used(self):
        self.save("2026-10-24-214000", "priya", ended_ago=400, chunks=[("Me", "old call"), ("Partner", "ok")])
        self.save("2026-10-24-215000", "jake", ended_ago=200)
        self.save("2026-10-24-215100", "priya", ended_ago=100, chunks=[("Me", "the last one"), ("Partner", "got it")])

        out = self.run_resume(self.config())

        self.assertIn("the last one", out.system_instruction)
        self.assertNotIn("old call", out.system_instruction)

    def test_ms_park_free_talk_uses_her_last_call(self):
        self.save("2026-10-24-215011", None, ended_ago=120, mission="Free Talk: my week", chunks=[("Me", "I went hiking"), ("Partner", "Nice!")])
        self.save("2026-10-24-215200", "priya", ended_ago=20)
        config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "freetalk"})

        out = self.run_resume(config)

        self.assertIn("I went hiking", out.system_instruction)
        self.assertIn("Ms. Park: Nice!", out.system_instruction)
        self.assertNotIn("line 19", out.system_instruction)

    def test_ms_park_mission_and_small_talk_do_not_resume(self):
        self.save("2026-10-24-215011", None, ended_ago=120, mission="Free Talk: my week")
        for mode in ("mission", "smalltalk", "teachback"):
            config = parse_call_config({"system_instruction": INSTRUCTION, "mode": mode})
            self.assertEqual(self.run_resume(config).system_instruction, INSTRUCTION, mode)

    def test_friend_mission_calls_never_resume(self):
        self.save("2026-10-24-215011", "priya", ended_ago=60)
        config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "mission", "partner": "priya"})

        self.assertEqual(self.run_resume(config).system_instruction, INSTRUCTION)

    def test_previous_call_without_learner_speech_is_skipped(self):
        self.save("2026-10-24-215011", "priya", ended_ago=60, chunks=[("Partner", "Hello?"), ("Partner", "Anyone there?")])

        self.assertEqual(self.run_resume(self.config()).system_instruction, INSTRUCTION)

    def test_long_and_multiline_turns_are_cut_and_joined(self):
        long_line = "word " * 200
        path = self.save("2026-10-24-215011", "priya", ended_ago=60, chunks=[("Me", "hi")])
        path.write_text(path.read_text(encoding="utf-8") + f"**Partner:** first line\nsecond line\n**Me:** {long_line}\n", encoding="utf-8")
        os.utime(path, (NOW - 60, NOW - 60))

        turns_ = resume.last_turns(path)

        self.assertEqual(turns_[1], ("Partner", "first line second line"))
        self.assertTrue(len(turns_[2][1]) <= resume.TURN_MAX)

    def test_instruction_is_validated_before_the_block_is_added(self):
        self.save("2026-10-24-215011", "priya", ended_ago=60)
        config = self.config()

        out = self.run_resume(config)

        self.assertEqual(config.system_instruction, INSTRUCTION)
        self.assertEqual((out.mode, out.partner, out.voice), (config.mode, config.partner, config.voice))


class OfferWiringTest(unittest.TestCase):
    def test_offer_hands_the_resumed_instruction_to_the_bot(self):
        from unittest import mock

        from fastapi.testclient import TestClient

        from server import main

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "2026-10-24-215011.md"
            path.write_text(transcript("priya", turns=[("Me", "I run a Go club"), ("Partner", "Wow!")]), encoding="utf-8")
            os.utime(path, (time.time() - 60, time.time() - 60))
            captured = {}

            async def fake_handle(request, webrtc_connection_callback):
                await webrtc_connection_callback(object())
                return {"sdp": "x", "type": "answer", "pc_id": "p1"}

            body = {"sdp": "v=0", "type": "offer", "request_data": {"system_instruction": INSTRUCTION, "mode": "smalltalk", "partner": "priya"}}
            with mock.patch.dict(os.environ, {"TRANSCRIPT_DIR": tmp}), mock.patch.object(main._webrtc, "handle_web_request", fake_handle), mock.patch.object(
                main, "run_bot", side_effect=lambda conn, cfg: captured.setdefault("config", cfg)
            ):
                res = TestClient(main.app).post("/api/offer", json=body)

            self.assertEqual(res.status_code, 200)
            instruction = captured["config"].system_instruction
            self.assertTrue(instruction.startswith(INSTRUCTION))
            self.assertIn("Learner: I run a Go club", instruction)


if __name__ == "__main__":
    unittest.main()

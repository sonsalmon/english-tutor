import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import main, people
from server.partner_memory import PARTNER_IDS


def transcript(started, mission="Small Talk", duration="4m 0s", partner=None):
    partner_line = f"- partner: {partner}\n" if partner else ""
    return (
        f"# Call {started}\n- mission: {mission}\n- model: test-model\n"
        f"- duration: {duration}\n- completed: yes\n- coach: 0\n{partner_line}\n**Me:** Hello\n"
    )


class PeopleTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.sessions = root / "sessions"
        self.chats = root / "chats"
        self.sessions.mkdir()
        self.chats.mkdir()
        env = {
            "TRANSCRIPT_DIR": str(self.sessions),
            "TUTORING_DIR": str(root / "tutoring"),
            "TEACHBACK_DIR": str(root / "teachback"),
            "CHAT_DIR": str(self.chats),
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def add_call(self, stem, started, **kwargs):
        (self.sessions / f"{stem}.md").write_text(transcript(started, **kwargs), encoding="utf-8")

    def add_chat(self, partner, *messages):
        lines = "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages)
        (self.chats / f"{partner}.jsonl").write_text(lines, encoding="utf-8")

    def by_id(self):
        return {p["id"]: p for p in people.build_people()}

    def test_router_is_mounted_on_the_app(self):
        self.assertIn("/api/people", {route.path for route in main.app.routes})

    def test_lists_park_first_then_every_friend_without_hiding_any(self):
        self.assertEqual([p["id"] for p in people.build_people()], ["park", *PARTNER_IDS])

    def test_person_with_no_call_and_no_chat_is_all_null(self):
        jake = self.by_id()["jake"]

        self.assertEqual(jake, {"id": "jake", "last_call": None, "last_message": None, "call_count": 0, "last_at": None})

    def test_calls_go_to_their_partner_and_park_gets_the_unlabelled_ones(self):
        self.add_call("2026-10-18-084000", "2026-10-18 08:40", partner="jake")
        self.add_call("2026-10-20-210300", "2026-10-20 21:03", partner="jake", duration="7m 10s")
        self.add_call("2026-10-19-100000", "2026-10-19 10:00", mission="Ordering coffee")

        found = self.by_id()

        self.assertEqual(found["jake"]["call_count"], 2)
        self.assertEqual(
            found["jake"]["last_call"],
            {"stem": "2026-10-20-210300", "started_at": "2026-10-20 21:03", "mission": "Small Talk", "duration_sec": 430},
        )
        self.assertEqual(found["park"]["call_count"], 1)
        self.assertEqual(found["park"]["last_call"]["stem"], "2026-10-19-100000")
        self.assertEqual(found["priya"]["call_count"], 0)

    def test_last_at_is_the_later_of_the_call_and_the_chat_and_sorts_as_time(self):
        self.add_call("2026-10-20-210300", "2026-10-20 21:03", partner="jake")
        self.add_chat(
            "jake",
            {"role": "me", "text": "hey", "at": "2026-10-20T08:00:00+09:00"},
            {"role": "friend", "text": "yo " + "x" * 300, "at": "2026-10-21T07:30:00+09:00"},
        )
        self.add_chat("priya", {"role": "me", "text": "hi", "at": "2026-10-20T22:00:00+09:00"})
        self.add_call("2026-10-20-150000", "2026-10-20 15:00", partner="brian")

        found = self.by_id()

        self.assertEqual(found["jake"]["last_at"], "2026-10-21T07:30:00+09:00")
        self.assertEqual(found["jake"]["last_message"]["role"], "friend")
        self.assertEqual(len(found["jake"]["last_message"]["text"]), people.PREVIEW_CHARS)
        self.assertEqual(found["brian"]["last_at"], "2026-10-20T15:00:00+09:00")
        ordered = sorted((p for p in found.values() if p["last_at"]), key=lambda p: p["last_at"], reverse=True)
        self.assertEqual([p["id"] for p in ordered], ["jake", "priya", "brian"])

    def test_park_never_has_a_chat_message(self):
        self.assertIsNone(self.by_id()["park"]["last_message"])

    def test_endpoint_wraps_the_list(self):
        self.add_call("2026-10-20-210300", "2026-10-20 21:03", partner="jake")

        body = asyncio.run(people.people_endpoint())

        self.assertEqual(len(body["people"]), 1 + len(PARTNER_IDS))


if __name__ == "__main__":
    unittest.main()

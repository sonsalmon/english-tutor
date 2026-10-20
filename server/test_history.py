import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import history


def transcript(started, mission="Ordering coffee", duration="2m 30s", completed="yes"):
    return (
        f"# Call {started}\n- mission: {mission}\n- model: test-model\n"
        f"- duration: {duration}\n- completed: {completed}\n- coach: 0\n\n**Me:** Hello\n"
    )


class HistoryDirs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.sessions = root / "sessions"
        self.tutoring = root / "tutoring"
        self.teachback = root / "teachback"
        for d in (self.sessions, self.tutoring, self.teachback):
            d.mkdir()
        env = {
            "TRANSCRIPT_DIR": str(self.sessions),
            "TUTORING_DIR": str(self.tutoring),
            "TEACHBACK_DIR": str(self.teachback),
        }
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def add_call(self, stem, started, **kwargs):
        (self.sessions / f"{stem}.md").write_text(transcript(started, **kwargs), encoding="utf-8")


class HistoryTest(HistoryDirs):
    def test_list_parses_fields(self):
        self.add_call("2026-10-20-090000", "2026-10-20 09:00", duration="2m 30s", completed="no")

        [call] = history.list_calls()

        self.assertEqual(
            call,
            {
                "stem": "2026-10-20-090000",
                "started_at": "2026-10-20 09:00",
                "mission": "Ordering coffee",
                "duration_sec": 150,
                "completed": False,
                "has_tutoring": False,
                "kind": "call",
            },
        )

    def test_list_is_newest_first_and_limited(self):
        self.add_call("2026-10-18-080000", "2026-10-18 08:00")
        self.add_call("2026-10-20-090000", "2026-10-20 09:00")
        self.add_call("2026-10-19-100000", "2026-10-19 10:00")

        self.assertEqual(
            [c["stem"] for c in history.list_calls()],
            ["2026-10-20-090000", "2026-10-19-100000", "2026-10-18-080000"],
        )
        self.assertEqual([c["stem"] for c in history.list_calls(limit=1)], ["2026-10-20-090000"])

    def test_totals_math(self):
        self.add_call("2026-10-20-090000", "2026-10-20 09:00", duration="1m 40s")
        self.add_call("2026-10-20-180000", "2026-10-20 18:00", duration="0m 50s")
        self.add_call("2026-10-18-080000", "2026-10-18 08:00", duration="2m 0s")
        self.add_call("2026-10-01-080000", "2026-10-01 08:00", duration="0m 5s")

        result = history.totals(now=datetime(2026, 10, 20, 12, 0))

        # 100 + 50 + 120 + 5 = 275초 -> 4분(내림), 날짜 3개, 최근 7일 통화 3개
        self.assertEqual(result, {"calls": 4, "minutes": 4, "days": 3, "week": 3})

    def test_totals_empty(self):
        self.assertEqual(history.totals(), {"calls": 0, "minutes": 0, "days": 0, "week": 0})

    def test_teachback_kind_and_tutoring_flag(self):
        self.add_call("2026-10-20-090000", "2026-10-20 09:00")
        self.add_call("2026-10-20-100000", "2026-10-20 10:00")
        self.add_call("2026-10-20-110000", "2026-10-20 11:00")
        (self.teachback / "2026-10-20-090000.json").write_text("{}", encoding="utf-8")
        (self.tutoring / "2026-10-20-100000.json").write_text("{}", encoding="utf-8")

        by_stem = {c["stem"]: c for c in history.list_calls()}

        self.assertEqual((by_stem["2026-10-20-090000"]["kind"], by_stem["2026-10-20-090000"]["has_tutoring"]), ("teachback", True))
        self.assertEqual((by_stem["2026-10-20-100000"]["kind"], by_stem["2026-10-20-100000"]["has_tutoring"]), ("call", True))
        self.assertEqual((by_stem["2026-10-20-110000"]["kind"], by_stem["2026-10-20-110000"]["has_tutoring"]), ("call", False))

    def test_small_talk_kind_and_totals_still_cover_all_calls(self):
        self.add_call("2026-10-20-090000", "2026-10-20 09:00", mission="Small Talk", duration="5m 0s")
        self.add_call("2026-10-20-100000", "2026-10-20 10:00", mission="Small Talk")
        self.add_call("2026-10-20-110000", "2026-10-20 11:00")
        (self.teachback / "2026-10-20-100000.json").write_text("{}", encoding="utf-8")

        by_stem = {c["stem"]: c for c in history.list_calls()}

        self.assertEqual(by_stem["2026-10-20-090000"]["kind"], "smalltalk")
        self.assertEqual(by_stem["2026-10-20-100000"]["kind"], "teachback")
        self.assertEqual(by_stem["2026-10-20-110000"]["kind"], "call")
        self.assertEqual(history.totals(datetime(2026, 10, 21, 9, 0))["calls"], 3)

    def test_unparsable_files_are_skipped(self):
        self.add_call("2026-10-20-090000", "2026-10-20 09:00")
        (self.sessions / "2026-10-20-100000.md").write_text("not a transcript\n", encoding="utf-8")
        (self.sessions / "2026-10-20-110000.md").write_text("# Call 2026-10-20 11:00\n- mission: x\n", encoding="utf-8")
        (self.sessions / "2026-10-20-120000.md").write_bytes(b"\xff\xfe\x00")
        (self.sessions / "notes.md").write_text(transcript("2026-10-20 13:00"), encoding="utf-8")

        self.assertEqual([c["stem"] for c in history.list_calls()], ["2026-10-20-090000"])
        self.assertEqual(history.totals()["calls"], 1)

    def test_load_call_returns_tutoring(self):
        self.add_call("2026-10-20-090000", "2026-10-20 09:00")
        payload = {"corrections": [{"said": "a", "better": "b", "why": "c"}]}
        (self.tutoring / "2026-10-20-090000.json").write_text(json.dumps(payload), encoding="utf-8")

        result = history.load_call("2026-10-20-090000")

        self.assertEqual(result["call"]["mission"], "Ordering coffee")
        self.assertEqual(result["tutoring"], payload)

    def test_load_call_without_tutoring_is_none(self):
        self.add_call("2026-10-20-090000", "2026-10-20 09:00")

        self.assertIsNone(history.load_call("2026-10-20-090000")["tutoring"])

    def test_load_call_rejects_invalid_stem(self):
        self.add_call("2026-10-20-090000", "2026-10-20 09:00")
        for bad in ("../x", "2026-10-20-090000.md", "2026-10-20-090000\n", "２０２６-10-20-090000", "a/b", ""):
            with self.subTest(stem=bad):
                with self.assertRaises(ValueError):
                    history.load_call(bad)

    def test_load_call_unknown_stem(self):
        with self.assertRaises(FileNotFoundError):
            history.load_call("2026-10-20-090000")


class CallsHttpTest(HistoryDirs):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient

        from server import main

        self.client = TestClient(main.app)

    def test_list_and_detail_over_http(self):
        self.add_call("2026-10-20-090000", "2026-10-20 09:00")

        listing = self.client.get("/api/calls")
        detail = self.client.get("/api/calls/2026-10-20-090000")

        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()["totals"]["calls"], 1)
        self.assertEqual(detail.status_code, 200)
        self.assertIsNone(detail.json()["tutoring"])

    def test_status_time_limits_include_smalltalk(self):
        env = {"SESSION_TIME_LIMIT": "180", "TEACHBACK_TIME_LIMIT": "900"}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("SMALLTALK_TIME_LIMIT", None)
            limits = self.client.get("/api/status").json()["time_limits"]

        self.assertEqual(limits, {"call": 180, "teachback": 900, "smalltalk": 300})

    def test_bad_stem_is_400_and_unknown_stem_is_404_not_the_spa_page(self):
        self.assertEqual(self.client.get("/api/calls/not-a-stem").status_code, 400)
        self.assertEqual(self.client.get("/api/calls/2026-01-01-000000").status_code, 404)


if __name__ == "__main__":
    unittest.main()

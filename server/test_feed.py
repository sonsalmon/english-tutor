import asyncio
import hashlib
import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import clipdb, feed, known, main, readgloss


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


class FeedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.db = root / "captions.db"
        self.tutoring = root / "tutoring"
        self.tutoring.mkdir()
        self.known_path = root / "known.json"
        conn = clipdb.connect(self.db)
        self.addCleanup(conn.close)
        clipdb.upsert_channel(conn, "@c", "Channel", "tv")
        for i in range(1, 9):
            clipdb.save_video(
                conn,
                {"id": f"v{i}", "channel_handle": "@c", "title": f"Video {i}", "published": "2026-01-01T00:00:00Z", "duration_sec": 60},
                "ok",
                "auto",
                [
                    seg(1.0, 4.0, f"so we need to figure out the plan number {i}"),
                    seg(10.0, 13.0, f"I was going to call it a day at number {i} okay"),
                    seg(20.0, 23.0, f"it was a quiet evening for everybody here {i}"),
                ],
                "2026-10-20T00:00:00+00:00",
            )
        env = {"TUTORING_DIR": str(self.tutoring), "KNOWN_EXPRESSIONS_PATH": str(self.known_path), "CLIPDB_PATH": str(self.db)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_tutoring(self, name, **data):
        (self.tutoring / name).write_text(json.dumps(data), encoding="utf-8")

    def test_terms_from_wordbook_then_tutoring_without_known_or_duplicates(self):
        self.write_tutoring("2026-10-20-100000.json", us_style=[{"natural": "call it a day"}], vocab=[{"word": "figure out"}, {"word": "Circle back"}])
        self.write_tutoring("2026-10-20-100000.review.json", items={})
        known.add("figure out", "known", "2026-10-20-100000", path=self.known_path)

        terms = feed.collect_terms(["circle back", "short shift"], self.tutoring, self.known_path)

        self.assertEqual(terms, ["circle back", "short shift", "call it a day"])

    def test_mine_cards_come_first_one_per_video_and_marked_with_their_term(self):
        cards = feed.build_page(["figure out", "call it a day"], "mine", 4, set(), db_path=self.db, rng=random.Random(3))

        self.assertEqual(len(cards), 4)
        self.assertEqual(len({c["video_id"] for c in cards}), 4)
        mine = [c for c in cards if c["source"] == "mine"]
        self.assertEqual(len(mine), 4)
        for c in mine:
            self.assertIn(c["term"].split()[0], c["text"])
        self.assertEqual({c["term"] for c in mine}, {"figure out", "call it a day"})

    def test_seen_clips_and_their_videos_do_not_come_back(self):
        first = feed.build_page(["figure out"], "mine", 3, set(), db_path=self.db, rng=random.Random(4))
        seen = {c["id"] for c in first}
        second = feed.build_page(["figure out"], "mine", 3, seen, db_path=self.db, rng=random.Random(5))

        self.assertEqual(len(second), 3)
        self.assertFalse({c["video_id"] for c in first} & {c["video_id"] for c in second})
        self.assertFalse(seen & {c["id"] for c in second})

    def test_missing_terms_fill_with_random_browse_cards_up_to_the_limit(self):
        cards = feed.build_page(["no such expression anywhere"], "mine", 6, set(), db_path=self.db, rng=random.Random(6))

        self.assertEqual(len(cards), 6)
        self.assertTrue(all(c["source"] == "browse" and c["term"] is None for c in cards))

    def test_browse_mode_ignores_terms(self):
        cards = feed.build_page(["figure out"], "browse", 5, set(), db_path=self.db, rng=random.Random(7))

        self.assertEqual(len(cards), 5)
        self.assertTrue(all(c["source"] == "browse" for c in cards))

    def test_page_never_writes_the_database(self):
        before = hashlib.sha256(self.db.read_bytes()).hexdigest()
        feed.build_page(["figure out"], "mine", 6, set(), db_path=self.db, rng=random.Random(8))

        self.assertEqual(hashlib.sha256(self.db.read_bytes()).hexdigest(), before)


class FeedEndpointTest(unittest.TestCase):
    def test_router_is_mounted(self):
        self.assertIn("/api/feed", {route.path for route in main.app.routes})

    def test_no_database_is_not_available(self):
        with mock.patch.dict(os.environ, {"CLIPDB_PATH": "/nonexistent/captions.db"}):
            body = asyncio.run(feed.feed_endpoint())

        self.assertEqual(body, {"available": False, "clips": [], "terms": 0})

    def test_endpoint_clamps_limit_and_falls_back_to_mine_on_bad_filter(self):
        calls = []

        def fake_page(mode, limit, seen):
            calls.append((mode, limit, sorted(seen)))
            return {"available": True, "clips": [], "terms": 0}

        with mock.patch.object(feed, "_page", side_effect=fake_page):
            asyncio.run(feed.feed_endpoint(filter="bogus", limit=999, seen="a:1, b:2,,"))
            asyncio.run(feed.feed_endpoint(filter="browse", limit=0, seen=""))

        self.assertEqual(calls, [("mine", feed.PAGE_MAX, ["a:1", "b:2"]), ("browse", 1, [])])

    def test_saved_phrases_skip_bridge_off_and_one_word_entries(self):
        with mock.patch.object(readgloss, "bridge_snapshot", return_value=None):
            self.assertEqual(feed._saved_phrases(), [])
        state = {"phrases": {"a": {"text": "circle back", "ts": 2}, "b": {"text": "hello", "ts": 3}}}
        with mock.patch.object(readgloss, "bridge_snapshot", return_value=(state, None)):
            self.assertEqual(feed._saved_phrases(), ["circle back"])


if __name__ == "__main__":
    unittest.main()

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

from server import clipdb, embeds, feed, known, main, readgloss


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


class FeedGenreAndEmbedTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.db = root / "captions.db"
        self.conn = clipdb.connect(self.db)
        self.addCleanup(self.conn.close)
        clipdb.upsert_channel(self.conn, "@show", "Show", "tv")
        clipdb.upsert_channel(self.conn, "@lec", "Lecture", "daily")
        env = {"EMBED_CACHE_PATH": str(root / "embed.json"), "TUTORING_DIR": str(root), "KNOWN_EXPRESSIONS_PATH": str(root / "k.json"), "CLIPDB_PATH": str(self.db)}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)

    def add(self, vid, handle, text):
        clipdb.save_video(
            self.conn,
            {"id": vid, "channel_handle": handle, "title": vid, "published": "2026-01-01T00:00:00Z", "duration_sec": 60},
            "ok",
            "auto",
            [{"start": 1.0, "end": 4.0, "text": text}],
            "2026-10-20T00:00:00+00:00",
        )

    def fill(self, tv, lec, phrase="figure out"):
        for i in range(tv):
            self.add(f"show-{i:03d}-v", "@show", f"so we need to {phrase} the plan number {i}")
        for i in range(lec):
            self.add(f"lect-{i:03d}-v", "@lec", f"today we learn to {phrase} the plan number {i}")

    def test_lecture_channels_only_fill_in_when_nothing_else_is_left(self):
        self.fill(tv=3, lec=5)
        cards = feed.build_page(["figure out"], "mine", 6, set(), db_path=self.db, rng=random.Random(1))

        ids = [c["video_id"] for c in cards]
        self.assertEqual(len(cards), 6)
        self.assertEqual([i for i in ids[:3] if i.startswith("show")], ids[:3])
        self.assertTrue(all(i.startswith("lect") for i in ids[3:]))

    def test_a_term_that_only_a_lecture_channel_says_loses_to_browse_scenes_from_other_channels(self):
        for i in range(6):
            self.add(f"show-{i:03d}-v", "@show", f"this is an ordinary sentence number {i} on tv")
        self.add("lect-000-v", "@lec", "a rare gem of an expression for you today")
        cards = feed.build_page(["rare gem of an expression"], "mine", 4, set(), db_path=self.db, rng=random.Random(2))

        self.assertEqual(len(cards), 4)
        self.assertTrue(all(c["video_id"].startswith("show") for c in cards))
        self.assertTrue(all(c["source"] == "browse" for c in cards))

        cards = feed.build_page(["rare gem of an expression"], "mine", 12, set(), db_path=self.db, rng=random.Random(2))
        self.assertEqual(cards[-1]["video_id"], "lect-000-v")
        self.assertEqual(cards[-1]["source"], "mine")

    def test_browse_uses_lecture_scenes_only_when_the_other_channels_run_out(self):
        self.fill(tv=2, lec=4)
        cards = feed.build_page([], "browse", 5, set(), db_path=self.db, rng=random.Random(3))

        ids = [c["video_id"] for c in cards]
        self.assertEqual(len(ids), 5)
        self.assertTrue(all(i.startswith("show") for i in ids[:2]))
        self.assertTrue(all(i.startswith("lect") for i in ids[2:]))

    def test_mine_cards_always_contain_their_expression(self):
        self.add("show-aaa-v", "@show", "the universe is very big")
        self.add("show-bbb-v", "@show", "I study at the university now")
        cards = feed.build_page(["university"], "mine", 1, set(), db_path=self.db, rng=random.Random(1))

        self.assertEqual([(c["video_id"], c["source"]) for c in cards], [("show-bbb-v", "mine")])

    def test_blocked_videos_never_become_cards_and_cards_are_topped_up_from_the_overfetch(self):
        self.fill(tv=9, lec=0)
        calls = []

        def playable(ids):
            calls.append(set(ids))
            return {i for i in ids if i != "show-000-v"}

        cards = feed.build_page(["figure out"], "mine", 3, set(), db_path=self.db, rng=random.Random(4), playable=playable)
        browse = feed.build_page([], "browse", 3, set(), db_path=self.db, rng=random.Random(4), playable=playable)

        self.assertEqual(len(cards), 3)
        self.assertEqual(len(browse), 3)
        for card in cards + browse:
            self.assertNotEqual(card["video_id"], "show-000-v")
        self.assertEqual(len(calls), 2)

    def test_page_filters_with_the_embed_cache_and_one_batch_per_request(self):
        self.fill(tv=6, lec=0)
        urls = []

        def api(url):
            urls.append(url)
            ids = url.split("id=", 1)[1].split("&")[0].replace("%2C", ",").split(",")
            items = [{"id": i, "status": {"embeddable": i != "show-000-v"}} for i in ids]
            return 200, json.dumps({"items": items})

        with mock.patch.object(embeds, "_http_get", api), mock.patch.object(embeds.youtube, "api_key", return_value="k"), mock.patch.object(
            feed, "_saved_phrases", return_value=[]
        ):
            first = feed._page("browse", 6, set())
            ids = {c["video_id"] for c in first["clips"]}
            calls_after_first = len(urls)
            second = feed._page("browse", 6, set())

        self.assertNotIn("show-000-v", ids)
        self.assertEqual(calls_after_first, 1)
        self.assertEqual(len(urls), 1)
        self.assertNotIn("show-000-v", {c["video_id"] for c in second["clips"]})

    def test_blocked_video_reported_by_the_client_is_gone_from_the_next_page(self):
        self.fill(tv=2, lec=0)
        with mock.patch.object(embeds.youtube, "api_key", return_value=None), mock.patch.object(feed, "_saved_phrases", return_value=[]):
            self.assertTrue(embeds.mark_blocked("show-000-v"))
            page = feed._page("browse", 6, set())

        self.assertEqual([c["video_id"] for c in page["clips"]], ["show-001-v"])


if __name__ == "__main__":
    unittest.main()

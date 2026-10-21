import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import clipdb

# 실제 자동 자막(Speak English With Vanessa, GeQO2Twc8DA)의 앞부분. 줄 사이 " "는 원본 그대로다.
REAL_AUTO_VTT = "\n".join(
    [
        "WEBVTT",
        "Kind: captions",
        "Language: en",
        "",
        "00:00:00.000 --> 00:00:02.950 align:start position:0%",
        " ",
        "What<00:00:00.480><c> is</c><00:00:00.680><c> the</c><00:00:01.040><c> number</c><00:00:01.520><c> one</c><00:00:01.760><c> topic</c><00:00:02.440><c> that</c><00:00:02.800><c> they</c>",
        "",
        "00:00:02.950 --> 00:00:02.960 align:start position:0%",
        "What is the number one topic that they",
        " ",
        "",
        "00:00:02.960 --> 00:00:05.830 align:start position:0%",
        "What is the number one topic that they",
        "say<00:00:03.280><c> you</c><00:00:03.480><c> should</c><00:00:03.800><c> not</c><00:00:04.320><c> talk</c><00:00:04.640><c> about</c><00:00:05.240><c> in</c><00:00:05.400><c> polite</c>",
        "",
        "00:00:05.830 --> 00:00:05.840 align:start position:0%",
        "say you should not talk about in polite",
        " ",
        "",
        "00:00:05.840 --> 00:00:07.470 align:start position:0%",
        "say you should not talk about in polite",
        "conversations?",
        "",
        "00:00:07.470 --> 00:00:07.480 align:start position:0%",
        "conversations?",
        " ",
        "",
        "00:00:07.480 --> 00:00:10.110 align:start position:0%",
        "conversations?",
        "Well,<00:00:08.080><c> it's</c><00:00:08.440><c> politics.</c><00:00:09.520><c> And</c><00:00:09.760><c> what</c><00:00:09.920><c> are</c><00:00:10.000><c> we</c>",
        "",
        "00:00:10.110 --> 00:00:10.120 align:start position:0%",
        "Well, it's politics. And what are we",
        " ",
        "",
        "00:00:10.120 --> 00:00:13.150 align:start position:0%",
        "Well, it's politics. And what are we",
        "going<00:00:10.240><c> to</c><00:00:10.360><c> talk</c><00:00:10.600><c> about</c><00:00:10.880><c> today?</c><00:00:11.760><c> Politics.</c><00:00:13.040><c> I</c>",
        "",
    ]
)

MANUAL_VTT = """WEBVTT

00:00:01.000 --> 00:00:02.500
[Music]
&gt;&gt; No.

00:00:02.500 --> 00:00:04.000
No.

00:00:04.000 --> 00:00:06.000
Tom &amp; Jerry said so.
"""


def seg(start, end, text):
    return {"start": start, "end": end, "text": text}


class ParseVtt(unittest.TestCase):
    def test_rolling_duplicates_removed(self):
        segs = clipdb.parse_vtt(REAL_AUTO_VTT)
        joined = " ".join(s["text"] for s in segs)
        self.assertEqual(joined.count("number one topic"), 1)
        self.assertEqual(joined.count("polite"), 1)
        self.assertEqual(joined.count("Well, it's politics."), 1)
        self.assertNotIn("<", joined)

    def test_rolling_timing(self):
        segs = clipdb.parse_vtt(REAL_AUTO_VTT)
        self.assertEqual(segs[0]["start"], 0.0)
        self.assertEqual(segs[0]["end"], 7.48)
        self.assertEqual(
            segs[0]["text"],
            "What is the number one topic that they say you should not talk about in polite conversations?",
        )
        self.assertEqual(segs[1]["start"], 7.48)
        self.assertEqual(segs[1]["end"], 13.15)
        self.assertEqual(segs[1]["text"], "Well, it's politics. And what are we going to talk about today? Politics. I")

    def test_segments_ordered_and_not_overlapping(self):
        segs = clipdb.parse_vtt(REAL_AUTO_VTT)
        for a, b in zip(segs, segs[1:]):
            self.assertLessEqual(a["end"], b["start"])
        for s in segs:
            self.assertLess(s["start"], s["end"])
            self.assertLessEqual(s["end"] - s["start"], clipdb.HARD_MAX)

    def test_long_silent_cue_is_capped(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:30.000\nHello<00:00:00.500><c> there</c>\n"
        segs = clipdb.parse_vtt(vtt)
        self.assertEqual(segs, [seg(0.0, clipdb.HARD_MAX, "Hello there")])

    def test_rolling_autodetected_but_overridable(self):
        self.assertEqual(clipdb.parse_vtt(REAL_AUTO_VTT), clipdb.parse_vtt(REAL_AUTO_VTT, rolling=True))
        self.assertNotEqual(clipdb.parse_vtt(REAL_AUTO_VTT), clipdb.parse_vtt(REAL_AUTO_VTT, rolling=False))

    def test_manual_keeps_repeated_cues_and_cleans_text(self):
        segs = clipdb.parse_vtt(MANUAL_VTT)
        text = " ".join(s["text"] for s in segs)
        self.assertEqual(text, "No. No. Tom & Jerry said so.")
        self.assertEqual(segs[0]["start"], 1.0)

    def test_empty_input(self):
        self.assertEqual(clipdb.parse_vtt(""), [])
        self.assertEqual(clipdb.parse_vtt("WEBVTT\n\n"), [])


class SearchDb(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "sub" / "captions.db"
        conn = clipdb.connect(self.path)
        self.addCleanup(conn.close)
        self.conn = conn
        clipdb.upsert_channel(conn, "@office", "The Office", "tv")
        clipdb.upsert_channel(conn, "@vanessa", "Vanessa", "daily")
        self.save("v1", "@office", "Dinner scene", [
            seg(1.0, 4.0, "you know I really like this"),
            seg(9.0, 12.0, "you know you know it is true"),
            seg(20.0, 23.0, "nothing to see here"),
        ])
        self.save("v2", "@vanessa", "Daily talk", [seg(5.5, 8.0, "well you know she talks about politics")])
        self.save("v3", "@vanessa", "No match", [seg(0.0, 3.0, "completely unrelated words")])

    def save(self, vid, handle, title, segments, status="ok"):
        clipdb.save_video(
            self.conn,
            {"id": vid, "channel_handle": handle, "title": title, "published": "2026-01-01T00:00:00Z", "duration_sec": 60},
            status,
            "auto",
            segments,
            "2026-10-20T00:00:00+00:00",
        )

    def test_phrase_hit_has_expected_fields(self):
        hits = clipdb.search("really like this", path=self.path)
        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(
            hit,
            {
                "video_id": "v1",
                "title": "Dinner scene",
                "channel": "The Office",
                "genre": "tv",
                "start": 1.0,
                "end": 4.0,
                "text": "you know I really like this",
            },
        )

    def test_phrase_must_be_adjacent(self):
        self.assertEqual(clipdb.search("like really", path=self.path), [])

    def test_one_hit_per_video_and_limit(self):
        hits = clipdb.search("you know", path=self.path)
        self.assertEqual(sorted(h["video_id"] for h in hits), ["v1", "v2"])
        self.assertEqual(len(clipdb.search("you know", limit=1, path=self.path)), 1)
        self.assertEqual(clipdb.search("you know", limit=0, path=self.path), [])

    def test_bm25_prefers_denser_segment(self):
        hit = next(h for h in clipdb.search("you know", path=self.path) if h["video_id"] == "v1")
        self.assertEqual(hit["start"], 9.0)

    def test_genre_filter(self):
        hits = clipdb.search("you know", genre="daily", path=self.path)
        self.assertEqual([h["video_id"] for h in hits], ["v2"])
        self.assertEqual(clipdb.search("you know", genre="work", path=self.path), [])

    def test_stemming(self):
        hits = clipdb.search("talk about politic", path=self.path)
        self.assertEqual([h["video_id"] for h in hits], ["v2"])

    def test_quotes_and_operators_are_escaped(self):
        self.assertEqual(clipdb.search('"really" like', path=self.path)[0]["video_id"], "v1")
        self.assertEqual(clipdb.search('say "hello', path=self.path), [])
        self.assertEqual(clipdb.search("you OR NEAR(", path=self.path), [])
        self.assertEqual(clipdb.search("   ", path=self.path), [])
        self.assertEqual(clipdb.search("...", path=self.path), [])

    def test_resave_replaces_old_segments_in_index(self):
        self.save("v3", "@vanessa", "No match", [seg(0.0, 3.0, "brand new sentence")])
        self.assertEqual(clipdb.search("completely unrelated", path=self.path), [])
        self.assertEqual(clipdb.search("brand new", path=self.path)[0]["video_id"], "v3")

    def test_random_segments_are_sentence_length_one_per_video_and_read_only(self):
        import hashlib
        import random

        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        hits = clipdb.random_segments(10, rng=random.Random(1), path=self.path)

        self.assertEqual(sorted(h["video_id"] for h in hits), ["v1", "v2"])
        for h in hits:
            self.assertTrue(6 <= len(h["text"].split()) <= 20)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_random_segments_skip_excluded_videos_and_failed_videos(self):
        import random

        self.save("v4", "@office", "Broken", [seg(0.0, 3.0, "this one has six words in it")], status="error")
        hits = clipdb.random_segments(10, exclude_videos={"v1"}, rng=random.Random(2), path=self.path)

        self.assertEqual([h["video_id"] for h in hits], ["v2"])
        self.assertEqual(clipdb.random_segments(0, path=self.path), [])
        self.assertEqual(clipdb.random_segments(3, path=self.path.parent / "missing.db"), [])

    def test_available_and_env_path(self):
        self.assertTrue(clipdb.available(self.path))
        with mock.patch.dict(os.environ, {"CLIPDB_PATH": str(self.path)}):
            self.assertTrue(clipdb.available())
            self.assertEqual(clipdb.search("nothing to see")[0]["video_id"], "v1")


class MissingOrEmptyDb(unittest.TestCase):
    def test_missing_db_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.db"
            self.assertFalse(clipdb.available(missing))
            self.assertEqual(clipdb.search("you know", path=missing), [])
            with mock.patch.dict(os.environ, {"CLIPDB_PATH": str(missing)}):
                self.assertFalse(clipdb.available())
                self.assertEqual(clipdb.search("you know"), [])

    def test_empty_db_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "empty.db"
            clipdb.connect(path).close()
            self.assertFalse(clipdb.available(path))
            self.assertEqual(clipdb.search("you know", path=path), [])

    def test_non_database_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "junk.db"
            path.write_text("not a database", encoding="utf-8")
            self.assertFalse(clipdb.available(path))
            self.assertEqual(clipdb.search("you know", path=path), [])


if __name__ == "__main__":
    unittest.main()

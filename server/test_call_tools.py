import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import call_bot, call_tools, clipdb
from server.call_bot import CallConfig

PUBLIC = lambda host, port: ["93.184.216.34"]  # noqa: E731


def transcript(started: str, partner, turns) -> str:
    head = [f"# Call {started[:16]}", "- mission: Small Talk", "- model: test", "- voice: Leda"]
    if partner:
        head.append(f"- partner: {partner}")
    head += ["- duration: 1m 0s", "- completed: no", "- coach: 0", ""]
    return "\n".join(head + [f"**{label}:** {text}" for label, text in turns]) + "\n"


class TranscriptSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.sessions = Path(self.tmp.name) / "sessions"
        self.sessions.mkdir()
        self.chats = Path(self.tmp.name) / "chats"
        self.chats.mkdir()
        patcher = mock.patch.dict(os.environ, {"CHAT_DIR": str(self.chats), "TRANSCRIPT_DIR": str(self.sessions)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write("2026-10-24-120000", "2026-10-24 12:00:00", "priya", [
            ("Me", "Hi Priya."),
            ("Partner", "Hello! How was your week?"),
            ("Me", "Good. I joined a Go club at my church last week."),
            ("Partner", "A Go club, that sounds fun!"),
            ("Me", "We play baduk on Saturday afternoons."),
            ("Partner", "Is it hard to learn?"),
            ("Me", "A little. The old men are patient."),
        ])
        self.write("2026-10-22-090000", "2026-10-22 09:00:00", "jake", [
            ("Me", "I went hiking near Seoul."),
            ("Partner", "Nice, which mountain?"),
            ("Me", "Bukhansan. My church group goes there."),
        ])
        self.write("2026-10-20-100000", "2026-10-20 10:00:00", None, [
            ("Me", "I need to ask my manager about the invoice deadline."),
            ("Partner", "Try asking: could we move it by a day?"),
        ])
        self.write("2026-10-24-130000", "2026-10-24 13:00:00", "priya", [
            ("Me", "I shared this one."),
            ("Me (shared)", "https://youtu.be/abcdefghijk — Sourdough for beginners"),
            ("Partner (shared clip)", '"all of a sudden" — Some Show / Some Channel https://www.youtube.com/watch?v=zzzzzzzzzzz&t=12s'),
        ])
        (self.chats / "priya.jsonl").write_text(
            json.dumps({"role": "me", "text": "My sister plays the violin in Busan.", "at": "2026-10-21T08:00:00+09:00"}) + "\n"
            + json.dumps({"role": "friend", "text": "Oh, a violinist! Does she perform?", "at": "2026-10-21T08:01:00+09:00"}) + "\n",
            encoding="utf-8",
        )
        (self.chats / "jake.jsonl").write_text(
            json.dumps({"role": "me", "text": "My brother plays the cello.", "at": "2026-10-21T09:00:00+09:00"}) + "\n", encoding="utf-8"
        )

    def write(self, stem, started, partner, turns):
        if turns is None:
            return
        (self.sessions / f"{stem}.md").write_text(transcript(started, partner, turns), encoding="utf-8")

    def search(self, query, partner):
        return call_tools.search_transcripts(query, call_tools.load_docs(partner, self.sessions))

    def test_go_club_is_found_verbatim_with_neighbouring_turns(self):
        result = self.search("Go club church", "priya")

        self.assertEqual(result[0]["date"], "2026-10-24 12:00")
        self.assertEqual(result[0]["with"], "Priya")
        self.assertIn("Learner: Good. I joined a Go club at my church last week.", result[0]["text"])
        self.assertIn("Priya: A Go club, that sounds fun!", result[0]["text"])
        self.assertIn("Learner: We play baduk on Saturday afternoons.", result[0]["text"])

    def test_friend_only_sees_own_calls_and_own_chat(self):
        jake_church = self.search("church", "jake")
        self.assertEqual([r["with"] for r in jake_church], ["Jake"])
        self.assertNotIn("Go club", json.dumps(jake_church))

        self.assertEqual(self.search("violin", "priya")[0]["source"], "chat")
        self.assertEqual(self.search("violin", "jake"), [])
        self.assertEqual(self.search("cello", "priya"), [])
        self.assertEqual(self.search("cello", "jake")[0]["source"], "chat")

    def test_ms_park_searches_every_call_but_not_friend_chats(self):
        self.assertEqual(self.search("invoice deadline", None)[0]["with"], "Ms. Park")
        self.assertEqual(self.search("baduk", None)[0]["with"], "Priya")
        self.assertEqual(self.search("violin", None), [])

    def test_friend_does_not_see_ms_park_calls(self):
        self.assertEqual(self.search("invoice", "priya"), [])

    def test_rare_word_beats_common_word_and_recent_wins_a_tie(self):
        results = self.search("church baduk", "priya")
        self.assertIn("baduk", results[0]["text"])

        both = call_tools.search_transcripts("church", call_tools.load_docs(None, self.sessions))
        self.assertEqual([r["date"] for r in both], sorted((r["date"] for r in both), reverse=True))

    def test_shared_items_are_searchable_and_labelled(self):
        found = self.search("sourdough", "priya")

        self.assertIn("Learner (shared a link or message): https://youtu.be/abcdefghijk", found[0]["text"])
        self.assertIn("Priya (shared a clip)", found[0]["text"])

    def test_no_match_and_stopword_only_queries_return_nothing(self):
        self.assertEqual(self.search("do you remember what I told you", "priya"), [])
        self.assertEqual(self.search("zebra", "priya"), [])
        self.assertEqual(call_tools.recall("zebra", "priya", self.sessions)["status"], "not_found")

    def test_snippets_are_capped_in_count_and_total_length(self):
        for day in range(10, 20):
            long_line = "We talked about the garden and the tomato plants for a very long time. " * 6
            self.write(f"2026-10-{day}-080000", f"2026-10-{day} 08:00:00", "brian", [("Me", long_line), ("Partner", long_line), ("Me", long_line), ("Partner", long_line), ("Me", long_line)])

        results = self.search("tomato garden", "brian")

        self.assertEqual(len(results), call_tools.RECALL_MAX_SNIPPETS)
        total = sum(len(r["text"]) + len(r["date"]) + len(r["with"]) + len(r["source"]) for r in results)
        self.assertLessEqual(total, call_tools.RECALL_MAX_CHARS)
        self.assertTrue(all(r["text"] for r in results))

    def test_korean_keywords_match(self):
        self.write("2026-10-25-100000", "2026-10-25 10:00:00", "jake", [("Me", "저는 바둑 동호회에 들어갔어요."), ("Partner", "Oh nice!")])

        self.assertIn("바둑", self.search("바둑", "jake")[0]["text"])

    def test_recall_result_shape(self):
        result = call_tools.recall("Go club", "priya", self.sessions)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(set(result["snippets"][0]), {"date", "with", "source", "text"})


class UrlSafetyTest(unittest.TestCase):
    def test_non_http_schemes_are_rejected(self):
        for url in ("ftp://example.com/a", "file:///etc/passwd", "javascript:alert(1)", "gopher://example.com", "//example.com"):
            with self.subTest(url=url), self.assertRaises(call_tools.UnsafeUrl):
                call_tools.check_url(url, PUBLIC)

    def test_private_loopback_and_link_local_addresses_are_blocked(self):
        for ip in ("127.0.0.1", "10.0.0.5", "192.168.1.9", "172.16.0.1", "169.254.169.254", "0.0.0.0", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1"):
            with self.subTest(ip=ip), self.assertRaises(call_tools.UnsafeUrl):
                call_tools.check_url("http://anything.example/", lambda h, p, ip=ip: [ip])

    def test_a_name_with_one_private_answer_is_blocked(self):
        with self.assertRaises(call_tools.UnsafeUrl):
            call_tools.check_url("https://rebind.example/", lambda h, p: ["93.184.216.34", "127.0.0.1"])

    def test_literal_private_hosts_are_blocked_without_a_custom_resolver(self):
        for url in ("http://127.0.0.1/", "http://localhost/", "http://[::1]/", "http://2130706433/", "http://10.1.2.3:8080/"):
            with self.subTest(url=url), self.assertRaises(call_tools.UnsafeUrl):
                call_tools.check_url(url)

    def test_credentials_and_odd_ports_are_blocked(self):
        for url in ("http://user:pw@example.com/", "https://example.com:22/", "https://example.com:6379/"):
            with self.subTest(url=url), self.assertRaises(call_tools.UnsafeUrl):
                call_tools.check_url(url, PUBLIC)

    def test_public_https_url_passes_and_keeps_path_and_query(self):
        target = call_tools.check_url("https://example.com/a/b?x=1", PUBLIC)

        self.assertEqual((target.scheme, target.host, target.port, target.path, target.ips), ("https", "example.com", 443, "/a/b?x=1", ("93.184.216.34",)))

    def test_redirect_to_a_private_address_is_blocked(self):
        def resolver(host, port):
            return ["10.0.0.9"] if host == "internal.example" else ["93.184.216.34"]

        def http_get(target, timeout):
            return 302, {"location": "http://internal.example/admin"}, b""

        with self.assertRaises(call_tools.UnsafeUrl):
            call_tools.fetch_text("https://public.example/", http_get=http_get, resolver=resolver)

    def test_redirect_loop_and_non_text_responses_fail(self):
        with self.assertRaises(call_tools.FetchError):
            call_tools.fetch_text("https://a.example/", http_get=lambda t, s: (301, {"location": "https://a.example/"}, b""), resolver=PUBLIC)
        with self.assertRaises(call_tools.FetchError):
            call_tools.fetch_text("https://a.example/x.zip", http_get=lambda t, s: (200, {"content-type": "application/zip"}, b"PK"), resolver=PUBLIC)

    def test_link_context_returns_an_error_instead_of_raising_for_private_urls(self):
        ctx = call_tools.link_context("http://127.0.0.1:8080/secret")

        self.assertFalse(ctx.ok)
        self.assertTrue(ctx.error)


class ShareTest(unittest.TestCase):
    def test_extract_urls_handles_punctuation_and_bare_hosts(self):
        found = call_tools.extract_urls("look: https://youtu.be/abc12345678, and (www.example.com/a?b=1). also youtube.com/watch?v=abc12345678!")

        self.assertEqual(found, ["https://youtu.be/abc12345678", "https://www.example.com/a?b=1", "https://youtube.com/watch?v=abc12345678"])
        self.assertEqual(call_tools.extract_urls("no link here, just words"), [])

    def test_youtube_id_forms(self):
        vid = "glh5aULdNMU"
        for url in (f"https://www.youtube.com/watch?v={vid}&t=3", f"https://youtu.be/{vid}?si=x", f"https://m.youtube.com/shorts/{vid}", f"https://www.youtube.com/embed/{vid}"):
            self.assertEqual(call_tools.youtube_id(url), vid, url)
        self.assertIsNone(call_tools.youtube_id("https://example.com/watch?v=" + vid))
        self.assertIsNone(call_tools.youtube_id("https://www.youtube.com/watch?v=short"))

    def test_plain_text_prompt(self):
        prompt = call_tools.share_prompt("I just got a new job [really]", None)

        self.assertTrue(prompt.startswith("[The learner sent a message: I just got a new job (really)"))
        self.assertEqual(prompt.count("["), 1)

    def test_page_is_read_into_title_and_text_within_the_limit(self):
        page = (
            "<html><head><title>Best sourdough tips</title><meta name='description' content='Easy bread'>"
            "<style>body{color:red}</style><script>alert('x')</script></head>"
            "<body><h1>Sourdough</h1><p>Feed your starter daily.</p>" + "<p>" + "word " * 2000 + "</p></body></html>"
        )

        ctx = call_tools.link_context(
            "https://bread.example/tips", http_get=lambda t, s: (200, {"content-type": "text/html; charset=utf-8"}, page.encode()), resolver=PUBLIC
        )

        self.assertTrue(ctx.ok)
        self.assertEqual(ctx.title, "Best sourdough tips")
        self.assertIn("Feed your starter daily.", ctx.excerpt)
        self.assertNotIn("alert", ctx.excerpt)
        self.assertNotIn("color:red", ctx.excerpt)
        self.assertLessEqual(len(ctx.excerpt), call_tools.PAGE_TEXT_MAX)

    def test_link_prompt_carries_title_excerpt_and_the_learners_own_words(self):
        ctx = call_tools.LinkContext("https://bread.example/tips", "page", "Best sourdough tips", "Feed your starter daily.")

        prompt = call_tools.share_prompt("check this https://bread.example/tips it is great", ctx)

        self.assertIn("The learner just sent you a link: Best sourdough tips - Feed your starter daily.", prompt)
        self.assertIn('The learner wrote: "check this it is great".', prompt)
        self.assertIn("React to it like a friend who opened it, and talk about it.", prompt)
        self.assertEqual(call_tools.share_record_text("https://bread.example/tips", ctx), "https://bread.example/tips — Best sourdough tips")
        self.assertEqual(call_tools.share_record_text("check https://bread.example/tips", ctx), 'https://bread.example/tips — Best sourdough tips ("check")')

    def test_unreadable_link_prompt_says_so(self):
        prompt = call_tools.share_prompt("https://x.example/a", call_tools.LinkContext("https://x.example/a", error="HTTP 404"))

        self.assertIn("could not open it", prompt)

    def test_youtube_context_uses_title_description_and_english_captions(self):
        vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:04.000\nWelcome to my video about sourdough starters.\n\n00:00:04.000 --> 00:00:08.000\nFirst you need flour and water.\n"
        info = {
            "title": "Sourdough for beginners",
            "description": "A slow video about bread. " * 50,
            "automatic_captions": {"fr": [{"ext": "vtt", "url": "https://yt.example/fr"}], "en": [{"ext": "vtt", "url": "https://yt.example/en"}]},
        }
        seen = []

        def http_get(target, timeout):
            seen.append(target.path)
            return 200, {"content-type": "text/vtt; charset=utf-8"}, vtt.encode()

        ctx = call_tools.youtube_context("abcdefghijk", "https://youtu.be/abcdefghijk", info_fn=lambda v: info, http_get=http_get, resolver=PUBLIC)

        self.assertEqual(seen, ["/en"])
        self.assertEqual(ctx.title, "Sourdough for beginners")
        self.assertIn("Captions: Welcome to my video about sourdough starters. First you need flour and water.", ctx.excerpt)
        self.assertLessEqual(len(ctx.excerpt), call_tools.YT_DESCRIPTION_MAX + call_tools.YT_CAPTION_MAX + 20)

    def test_youtube_falls_back_to_the_caption_db_when_yt_dlp_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captions.db"
            conn = clipdb.connect(db)
            clipdb.upsert_channel(conn, "@show", "Some Show", "drama")
            clipdb.save_video(
                conn,
                {"id": "abcdefghijk", "channel_handle": "@show", "title": "The Pilot Episode"},
                "ok",
                "auto",
                [{"start": 0.0, "end": 4.0, "text": "We moved to Austin last month."}, {"start": 4.0, "end": 8.0, "text": "It is really hot here."}],
                "2026-10-24",
            )
            conn.close()

            def boom(video_id):
                raise RuntimeError("blocked")

            ctx = call_tools.youtube_context("abcdefghijk", "https://youtu.be/abcdefghijk", info_fn=boom, resolver=PUBLIC, db=db)

        self.assertTrue(ctx.ok)
        self.assertEqual(ctx.title, "The Pilot Episode")
        self.assertIn("We moved to Austin last month. It is really hot here.", ctx.excerpt)

    def test_share_text_is_cleaned_and_capped(self):
        self.assertEqual(call_tools.clean_share_text("  hi\x00 there  "), "hi there")
        self.assertEqual(call_tools.clean_share_text(None), "")
        self.assertEqual(len(call_tools.clean_share_text("x" * 5000)), call_tools.SHARE_TEXT_MAX)


class ShareClipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "captions.db"
        conn = clipdb.connect(self.db)
        clipdb.upsert_channel(conn, "@drama", "Drama Channel", "drama")
        clipdb.upsert_channel(conn, "@class", "English Class", "daily")
        stamp = "2026-10-24"
        clipdb.save_video(conn, {"id": "dramaVideo01", "channel_handle": "@drama", "title": "Drama Night"}, "ok", "auto",
                          [{"start": 10.0, "end": 14.0, "text": "And all of a sudden the lights went out in the whole house."}], stamp)
        clipdb.save_video(conn, {"id": "classVideo01", "channel_handle": "@class", "title": "Learn English Fast"}, "ok", "manual",
                          [{"start": 5.0, "end": 9.0, "text": "Today we learn the phrase all of a sudden and how to use it."}], stamp)
        clipdb.save_video(conn, {"id": "gardenVideo1", "channel_handle": "@drama", "title": "Garden Talk"}, "ok", "auto",
                          [{"start": 3.0, "end": 7.0, "text": "I planted tomatoes in my garden this spring."}], stamp)
        conn.close()

    def test_lecture_channels_are_skipped_when_a_natural_scene_exists(self):
        clip = call_tools.find_clip("all of a sudden", db=self.db, entries=[], rng=random.Random(1))

        self.assertEqual(clip["video_id"], "dramaVideo01")
        self.assertEqual(set(clip), {"video_id", "start", "end", "text", "title", "channel"})
        self.assertEqual((clip["start"], clip["end"], clip["title"], clip["channel"]), (10.0, 14.0, "Drama Night", "Drama Channel"))

    def test_native_expression_clip_comes_first_and_lecture_native_clips_are_skipped(self):
        entries = [{
            "expression": "all of a sudden",
            "key": "all of a sudden",
            "clips": [
                {"video_id": "classVideo01", "start": 5.0, "end": 9.0, "text": "Today we learn the phrase all of a sudden and how to use it.", "title": "Learn English Fast", "channel": "English Class"},
                {"video_id": "nativeVid001", "start": 1.0, "end": 4.0, "text": "It all of a sudden got quiet.", "title": "Native Scene", "channel": "Show"},
            ],
        }]

        clip = call_tools.find_clip("all of a sudden", db=self.db, entries=entries)

        self.assertEqual(clip["video_id"], "nativeVid001")

    def test_topic_falls_back_to_a_single_content_word(self):
        clip = call_tools.find_clip("my garden and plants", db=self.db, entries=[])

        self.assertEqual(clip["video_id"], "gardenVideo1")

    def test_already_shared_videos_are_not_repeated(self):
        self.assertIsNone(call_tools.find_clip("all of a sudden", {"dramaVideo01", "classVideo01"}, db=self.db, entries=[]))

    def test_lecture_scene_is_the_last_resort(self):
        clip = call_tools.find_clip("all of a sudden", {"dramaVideo01"}, db=self.db, entries=[])

        self.assertEqual(clip["video_id"], "classVideo01")

    def test_missing_db_and_empty_query_give_none(self):
        self.assertIsNone(call_tools.find_clip("all of a sudden", db=Path(self.tmp.name) / "none.db", entries=[]))
        self.assertIsNone(call_tools.find_clip("   ", db=self.db, entries=[]))

    def test_tool_result_shapes(self):
        clip = call_tools.find_clip("all of a sudden", db=self.db, entries=[])

        shared = call_tools.share_clip_result(clip)
        self.assertEqual((shared["status"], shared["line"], shared["title"], shared["channel"]), ("shared", clip["text"], "Drama Night", "Drama Channel"))
        self.assertNotIn("http", json.dumps(shared))
        self.assertEqual(call_tools.share_clip_result(None)["status"], "not_found")
        self.assertEqual(
            call_tools.clip_record_text(clip),
            '"And all of a sudden the lights went out in the whole house." — Drama Night / Drama Channel https://www.youtube.com/watch?v=dramaVideo01&t=10s',
        )


class LiveToolsTest(unittest.TestCase):
    def names(self, mode):
        tools = call_bot.live_tools(CallConfig(system_instruction="x", mode=mode))
        return None if tools is None else [t.name for t in tools.standard_tools]

    def test_every_mode_but_teachback_gets_recall_and_share_clip(self):
        self.assertIsNone(self.names("teachback"))
        for mode in ("smalltalk", "mission", "freetalk"):
            self.assertIn("recall_past_conversations", self.names(mode))
            self.assertIn("share_clip", self.names(mode))

    def test_complete_mission_stays_out_of_smalltalk(self):
        self.assertNotIn("complete_mission", self.names("smalltalk"))
        self.assertEqual(self.names("mission"), ["complete_mission", "recall_past_conversations", "share_clip"])

    def test_shared_notes_are_recorded_under_their_own_labels(self):
        record = call_bot.CallRecord()
        record.add_user("I love hiking in the mountains")
        record.add_note("Me (shared)", "https://youtu.be/abcdefghijk — Hiking")
        record.add_note("Partner (shared clip)", '"nice" — Show')

        self.assertEqual([s for s, _ in record.chunks], ["Me", "Me (shared)", "Partner (shared clip)"])
        self.assertTrue(record.learner_has_spoken())


if __name__ == "__main__":
    unittest.main()

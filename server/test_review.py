import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException

from server import known, review

STEM = "2026-10-20-090000"


class Req:
    def __init__(self, body, content_type="application/json"):
        self._body = body
        self.headers = {"content-type": content_type}

    async def json(self):
        return self._body


class ReviewTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.sessions = root / "sessions"
        self.sessions.mkdir()
        (self.sessions / f"{STEM}.md").write_text("**Me:** hi\n", encoding="utf-8")
        patcher = mock.patch.dict(
            os.environ,
            {
                "TRANSCRIPT_DIR": str(self.sessions),
                "TUTORING_DIR": str(root / "tutoring"),
                "KNOWN_EXPRESSIONS_PATH": str(root / "known.json"),
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        review._PENDING.clear()
        review._TIMERS.clear()
        self.addCleanup(review.configure, review._update_card)
        self.updates = []
        review.configure(lambda stem, tutoring: self.updates.append((stem, tutoring)))

    def known_keys(self):
        return [(e["key"], e["state"]) for e in known.load()]


class FlagTransitionsTest(ReviewTestBase):
    async def flag(self, kind, text, state):
        return await review.flag_endpoint(Req({"stem": STEM, "kind": kind, "text": text, "state": state}))

    async def test_known_and_misheard_are_remembered_and_added_to_the_store(self):
        await self.flag("correction", "I just started", "known")
        await self.flag("us_style", "Thanks for jumping on this", "misheard")

        items = (await review.review_endpoint(STEM))["items"]
        self.assertEqual(items, {"correction:i just started": "known", "us_style:thanks for jumping on this": "misheard"})
        self.assertEqual(self.known_keys(), [("i just started", "known"), ("thanks for jumping on this", "misheard")])

    async def test_saved_is_remembered_but_not_added_to_the_store(self):
        await self.flag("vocab", "short shift", "saved")

        self.assertEqual((await review.review_endpoint(STEM))["items"], {"vocab:short shift": "saved"})
        self.assertEqual(self.known_keys(), [])

    async def test_null_undoes_the_mark_and_the_store_entry(self):
        await self.flag("correction", "I just started", "known")

        res = await self.flag("correction", "I just started", None)

        self.assertEqual(res, {"status": "ok", "state": None})
        self.assertEqual((await review.review_endpoint(STEM))["items"], {})
        self.assertEqual(self.known_keys(), [])

    async def test_switching_from_known_to_misheard_keeps_one_store_entry(self):
        await self.flag("correction", "I just started", "known")
        await self.flag("correction", "I just started", "misheard")

        self.assertEqual(self.known_keys(), [("i just started", "misheard")])

    async def test_switching_from_known_to_saved_removes_the_store_entry(self):
        await self.flag("correction", "I just started", "known")
        await self.flag("correction", "I just started", "saved")

        self.assertEqual(self.known_keys(), [])
        self.assertEqual((await review.review_endpoint(STEM))["items"], {"correction:i just started": "saved"})

    async def test_same_text_in_different_kinds_is_marked_separately(self):
        await self.flag("correction", "circle back", "known")
        await self.flag("vocab", "circle back", "saved")

        self.assertEqual(
            (await review.review_endpoint(STEM))["items"],
            {"correction:circle back": "known", "vocab:circle back": "saved"},
        )

    async def test_no_marks_gives_an_empty_object(self):
        self.assertEqual(await review.review_endpoint(STEM), {"items": {}})


class FlagValidationTest(ReviewTestBase):
    async def status_of(self, body, content_type="application/json"):
        with self.assertRaises(HTTPException) as ctx:
            await review.flag_endpoint(Req(body, content_type))
        return ctx.exception.status_code

    async def test_bad_requests_get_400_unknown_call_404_and_non_json_415(self):
        good = {"stem": STEM, "kind": "correction", "text": "I just started", "state": "known"}
        self.assertEqual(await self.status_of({**good, "stem": "../x"}), 400)
        self.assertEqual(await self.status_of({**good, "kind": "pragmatics"}), 400)
        self.assertEqual(await self.status_of({**good, "state": "weird"}), 400)
        self.assertEqual(await self.status_of({k: v for k, v in good.items() if k != "state"}), 400)
        self.assertEqual(await self.status_of({**good, "text": "   "}), 400)
        self.assertEqual(await self.status_of({**good, "text": "x" * (review.MAX_TEXT + 1)}), 400)
        self.assertEqual(await self.status_of({**good, "text": "\ud55c\uad6d\uc5b4"}), 400)
        self.assertEqual(await self.status_of({**good, "stem": "2026-10-20-090001"}), 404)
        self.assertEqual(await self.status_of(good, "text/plain"), 415)
        self.assertEqual(await self.status_of([1]), 400)
        self.assertEqual(self.known_keys(), [])

    async def test_review_and_finish_reject_a_bad_stem(self):
        with self.assertRaises(HTTPException) as ctx:
            await review.review_endpoint("../x")
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            await review.finish_endpoint("nope", Req({}))
        self.assertEqual(ctx.exception.status_code, 400)


class FinishAndTimerTest(ReviewTestBase):
    TUTORING = {
        "corrections": [{"said": "a", "better": "I just started", "why": "x"}, {"said": "b", "better": "I got swamped", "why": "y"}],
        "us_style": [{"said": "s", "korean_way": "k", "natural": "Thanks for jumping on this", "why": "w"}],
    }

    async def test_finish_hands_over_the_pending_update_once_without_marked_items(self):
        review.defer_card_update(STEM, self.TUTORING)
        await review.flag_endpoint(Req({"stem": STEM, "kind": "correction", "text": "I just started", "state": "misheard"}))
        await review.flag_endpoint(Req({"stem": STEM, "kind": "us_style", "text": "Thanks for jumping on this", "state": "known"}))
        await review.flag_endpoint(Req({"stem": STEM, "kind": "correction", "text": "I got swamped", "state": "saved"}))

        first = await review.finish_endpoint(STEM, Req({}))
        second = await review.finish_endpoint(STEM, Req({}))

        self.assertEqual((first, second), ({"status": "scheduled"}, {"status": "nothing"}))
        self.assertEqual(len(self.updates), 1)
        stem, sent = self.updates[0]
        self.assertEqual(stem, STEM)
        self.assertEqual([c["better"] for c in sent["corrections"]], ["I got swamped"])
        self.assertEqual(sent["us_style"], [])
        self.assertEqual(len(self.TUTORING["corrections"]), 2)

    async def test_flagged_thinking_gap_is_dropped_from_the_card_update(self):
        tutoring = {**self.TUTORING, "thinking_gaps": [{"korean": "정신없다", "english": "I'm swamped"}, {"korean": "가다", "english": "go"}]}
        review.defer_card_update(STEM, tutoring)
        await review.flag_endpoint(Req({"stem": STEM, "kind": "thinking_gap", "text": "I'm swamped", "state": "misheard"}))
        await review.finish_endpoint(STEM, Req({}))
        self.assertEqual([g["english"] for g in self.updates[0][1]["thinking_gaps"]], ["go"])

    async def test_unmarked_tutoring_is_handed_over_unchanged(self):
        review.defer_card_update(STEM, self.TUTORING)
        review.finish(STEM)

        self.assertIs(self.updates[0][1], self.TUTORING)

    async def test_second_defer_for_the_same_call_keeps_the_first(self):
        review.defer_card_update(STEM, {"corrections": [], "marker": 1})
        review.defer_card_update(STEM, {"corrections": [], "marker": 2})
        review.finish(STEM)

        self.assertEqual([u[1]["marker"] for u in self.updates], [1])

    async def test_timer_hands_over_after_the_delay_when_finish_never_comes(self):
        with mock.patch.object(review, "CARD_DELAY_SEC", 0):
            review.defer_card_update(STEM, self.TUTORING)
            await review._TIMERS[STEM]

        self.assertEqual([u[0] for u in self.updates], [STEM])
        self.assertEqual(review._TIMERS, {})
        self.assertFalse(review.finish(STEM))

    async def test_finish_cancels_the_timer_so_nothing_runs_twice(self):
        with mock.patch.object(review, "CARD_DELAY_SEC", 3600):
            review.defer_card_update(STEM, self.TUTORING)
            timer = review._TIMERS[STEM]
            review.finish(STEM)
            with self.assertRaises(asyncio.CancelledError):
                await timer

        self.assertEqual(len(self.updates), 1)

    async def test_finish_without_pending_or_without_a_registered_hook_is_nothing(self):
        self.assertFalse(review.finish(STEM))
        review._update_card = None
        review._PENDING[STEM] = self.TUTORING
        self.assertFalse(review.finish(STEM))


def allow_all(ids):
    return set(ids)


class PhraseClipsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        env = mock.patch.dict(os.environ, {"EMBED_CACHE_PATH": str(self.root / "embed.json"), "CLIPDB_PATH": str(self.root / "captions.db")})
        env.start()
        self.addCleanup(env.stop)
        for patcher in (
            mock.patch.object(review.embeds, "_http_get", side_effect=AssertionError("network")),
            mock.patch.object(review.embeds.youtube, "api_key", return_value=None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def make_db(self, rows):
        conn = review.clipdb.connect(self.root / "captions.db")
        self.addCleanup(conn.close)
        review.clipdb.upsert_channel(conn, "@tv", "A Show", "tv")
        review.clipdb.upsert_channel(conn, "@lec", "A Lecture Channel", "daily")
        for vid, handle, text in rows:
            review.clipdb.save_video(
                conn,
                {"id": vid, "channel_handle": handle, "title": f"title {vid}", "published": "2026-01-01T00:00:00Z", "duration_sec": 60},
                "ok",
                "auto",
                [{"start": 3.0, "end": 6.0, "text": text}],
                "2026-10-20T00:00:00+00:00",
            )

    async def test_ok_returns_db_clips_with_the_matching_moment(self):
        hits = [{"video_id": "abc123", "title": "T", "channel": "C", "start": 12.7, "text": "so what do you do"}, {"title": "no id"}]
        with mock.patch.object(review.clipdb, "available", return_value=True), mock.patch.object(
            review.clipdb, "search", return_value=hits
        ) as search, mock.patch.object(review.embeds, "playable", allow_all):
            res = await review.phrase_clips_endpoint("  So, what do you do?  ", 99)

        search.assert_called_once_with("So, what do you do?", limit=review.MAX_PHRASE_CLIPS * review.PHRASE_OVERFETCH, tier="preferred")
        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(res["clips"]), 1)
        clip = res["clips"][0]
        self.assertEqual((clip["id"], clip["start"], clip["source"], clip["phrase"]), ("abc123", 12, "db", "So, what do you do?"))
        self.assertEqual(clip["thumbnail"], "https://i.ytimg.com/vi/abc123/mqdefault.jpg")

    async def test_no_db_hides_the_area_and_a_bad_query_is_no_query(self):
        with mock.patch.object(review.clipdb, "available", return_value=False), mock.patch.object(review.clipdb, "search") as search:
            self.assertEqual((await review.phrase_clips_endpoint("circle back", 3))["status"], "no_db")
            search.assert_not_called()
        for q in ("", "x", "\ud55c\uad6d\uc5b4 \ud45c\ud604", "w" * (review.MAX_PHRASE_QUERY + 1)):
            with mock.patch.object(review.clipdb, "search") as search:
                self.assertEqual((await review.phrase_clips_endpoint(q, 3))["status"], "no_query", q)
                search.assert_not_called()

    async def test_limit_is_clamped_to_at_least_one(self):
        with mock.patch.object(review.clipdb, "available", return_value=True), mock.patch.object(
            review.clipdb, "search", return_value=[]
        ) as search, mock.patch.object(review.embeds, "playable", allow_all):
            await review.phrase_clips_endpoint("circle back", 0)

        self.assertEqual(search.call_args_list[0].kwargs["limit"], review.PHRASE_OVERFETCH)

    async def test_only_captions_that_really_contain_the_phrase_come_back(self):
        # FTS stems "university" and "universe" alike, so the second row is a false hit the endpoint must drop.
        self.make_db(
            [
                ("vid-good1", "@tv", "I go to the university every day"),
                ("vid-fake1", "@tv", "the universe is very big"),
                ("vid-good2", "@tv", "she loves universities"),
            ]
        )
        with mock.patch.object(review.embeds, "playable", allow_all):
            res = await review.phrase_clips_endpoint("university", 5)

        self.assertEqual(res["status"], "ok")
        self.assertEqual({c["id"] for c in res["clips"]}, {"vid-good1", "vid-good2"})
        for clip in res["clips"]:
            self.assertTrue(review.clipdb.contains_phrase(clip["text"], "university"))

    async def test_long_caption_is_cut_around_the_phrase_so_it_stays_visible(self):
        self.make_db([("vid-show1", "@tv", "or a dog person I think I'm a dog person what do you do for work do you work from home or in an office")])
        with mock.patch.object(review.embeds, "playable", allow_all):
            res = await review.phrase_clips_endpoint("do you work from home", 3)

        text = res["clips"][0]["text"]
        self.assertTrue(review.clipdb.contains_phrase(text, "do you work from home"))
        self.assertLess(len(text.split()), 16)

    async def test_no_matching_caption_gives_an_empty_clip_list(self):
        self.make_db([("vid-fake1", "@tv", "the universe is very big")])
        with mock.patch.object(review.embeds, "playable", allow_all):
            res = await review.phrase_clips_endpoint("university", 3)

        self.assertEqual((res["status"], res["clips"]), ("ok", []))

    async def test_lecture_channel_clips_only_when_no_other_channel_has_the_phrase(self):
        self.make_db([("vid-lect1", "@lec", "do you work from home or not"), ("vid-show1", "@tv", "so do you work from home")])
        with mock.patch.object(review.embeds, "playable", allow_all):
            both = await review.phrase_clips_endpoint("do you work from home", 3)
        self.assertEqual([c["id"] for c in both["clips"]], ["vid-show1"])

        self.make_db([("vid-lect2", "@lec", "and then you take a long break")])
        with mock.patch.object(review.embeds, "playable", allow_all):
            only = await review.phrase_clips_endpoint("take a long break", 3)
        self.assertEqual([c["id"] for c in only["clips"]], ["vid-lect2"])

    async def test_blocked_videos_are_dropped_and_lecture_is_used_when_nothing_else_plays(self):
        self.make_db(
            [("vid-show1", "@tv", "so do you work from home"), ("vid-show2", "@tv", "hey do you work from home"), ("vid-lect1", "@lec", "do you work from home or not")]
        )
        with mock.patch.object(review.embeds, "playable", lambda ids: {i for i in ids if i != "vid-show1"}):
            res = await review.phrase_clips_endpoint("do you work from home", 3)
        self.assertEqual([c["id"] for c in res["clips"]], ["vid-show2"])

        with mock.patch.object(review.embeds, "playable", lambda ids: {i for i in ids if i.startswith("vid-lect")}):
            res = await review.phrase_clips_endpoint("do you work from home", 3)
        self.assertEqual([c["id"] for c in res["clips"]], ["vid-lect1"])

    async def test_client_blocked_video_is_left_out_of_the_next_request(self):
        self.make_db([("vid-show1", "@tv", "so do you work from home"), ("vid-show2", "@tv", "hey do you work from home")])
        res = await review.blocked_clip_endpoint(Req({"video_id": "vid-show1"}))
        self.assertEqual(res, {"status": "ok"})

        after = await review.phrase_clips_endpoint("do you work from home", 3)

        self.assertEqual([c["id"] for c in after["clips"]], ["vid-show2"])

    async def test_blocked_endpoint_rejects_bad_ids_and_non_json(self):
        for body in ({}, {"video_id": ""}, {"video_id": 5}, {"video_id": "../../etc"}, {"video_id": "x" * 40}):
            with self.assertRaises(HTTPException) as ctx:
                await review.blocked_clip_endpoint(Req(body))
            self.assertEqual(ctx.exception.status_code, 400, body)
        with self.assertRaises(HTTPException) as ctx:
            await review.blocked_clip_endpoint(Req({"video_id": "vid-show1"}, content_type="text/plain"))
        self.assertEqual(ctx.exception.status_code, 415)
        self.assertFalse((self.root / "embed.json").exists())


class RouterWiringTest(unittest.TestCase):
    def test_routes_are_registered_on_the_app(self):
        from server import main

        paths = {r.path for r in main.app.routes}
        self.assertTrue(
            {"/api/review/flag", "/api/calls/{stem}/review", "/api/calls/{stem}/review/finish", "/api/clips/phrase", "/api/clips/blocked"} <= paths
        )

    def test_main_registers_the_card_update_hook(self):
        from server import main

        self.assertIs(review._update_card, main._card_update_once)



class CorruptReviewFileTest(unittest.TestCase):
    def test_a_broken_or_unreadable_review_file_reads_as_empty_instead_of_failing(self):
        import os
        import tempfile
        from pathlib import Path
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {"TUTORING_DIR": tmp}):
                path = review.review_path("2026-10-21-221050")
                self.assertEqual(review.load_items("2026-10-21-221050"), {})
                path.write_text("{not json", encoding="utf-8")
                self.assertEqual(review.load_items("2026-10-21-221050"), {})
                path.write_text('{"items": "nope"}', encoding="utf-8")
                self.assertEqual(review.load_items("2026-10-21-221050"), {})
                path.unlink()
                path.mkdir()
                self.assertEqual(review.load_items("2026-10-21-221050"), {})
                review.apply_flag("2026-10-21-221051", "correction", "I agree", "known")
                self.assertEqual(review.load_items("2026-10-21-221051"), {"correction:i agree": "known"})


if __name__ == "__main__":
    unittest.main()

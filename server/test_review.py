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


class PhraseClipsTest(unittest.IsolatedAsyncioTestCase):
    async def test_ok_returns_db_clips_with_the_matching_moment(self):
        hits = [{"video_id": "abc123", "title": "T", "channel": "C", "start": 12.7, "text": "so what do you do"}, {"title": "no id"}]
        with mock.patch.object(review.clipdb, "available", return_value=True), mock.patch.object(
            review.clipdb, "search", return_value=hits
        ) as search:
            res = await review.phrase_clips_endpoint("  So, what do you do?  ", 99)

        search.assert_called_once_with("So, what do you do?", limit=review.MAX_PHRASE_CLIPS)
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
        ) as search:
            await review.phrase_clips_endpoint("circle back", 0)

        self.assertEqual(search.call_args.kwargs["limit"], 1)


class RouterWiringTest(unittest.TestCase):
    def test_routes_are_registered_on_the_app(self):
        from server import main

        paths = {r.path for r in main.app.routes}
        self.assertTrue(
            {"/api/review/flag", "/api/calls/{stem}/review", "/api/calls/{stem}/review/finish", "/api/clips/phrase"} <= paths
        )

    def test_main_registers_the_card_update_hook(self):
        from server import main

        self.assertIs(review._update_card, main._card_update_once)


if __name__ == "__main__":
    unittest.main()

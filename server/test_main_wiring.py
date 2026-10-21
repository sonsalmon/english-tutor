import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import main, pron, review

TRANSCRIPT = Path("/nonexistent/2026-10-20-090000.md")
TUTORING = {"corrections": [{"said": "I just start", "better": "I just started", "why": "x"}]}


def isolate_review_state(test):
    """튜터링·알려 준 표현 폴더를 임시 폴더로 돌리고 검토 대기 상태를 비운다."""
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    patcher = mock.patch.dict(
        os.environ, {"TUTORING_DIR": tmp.name, "KNOWN_EXPRESSIONS_PATH": str(Path(tmp.name) / "known.json")}
    )
    patcher.start()
    test.addCleanup(patcher.stop)
    review._PENDING.clear()
    review._TIMERS.clear()
    return Path(tmp.name)


class FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class TutorEndpointWiringTest(unittest.IsolatedAsyncioTestCase):
    def finish(self):
        return review.finish(TRANSCRIPT.stem)

    def setUp(self):
        main._TUTOR_CACHE.clear()
        main._PROFILE_UPDATED.clear()
        self.review_dir = isolate_review_state(self)
        patches = {
            "bridge": mock.patch("server.readgloss._request", return_value=None),
            "resolve": mock.patch.object(main, "_wait_and_resolve_transcript", return_value=TRANSCRIPT),
            "run": mock.patch.object(main, "run_tutoring", side_effect=lambda path: (dict(TUTORING), True)),
            "schedule": mock.patch.object(main, "_schedule_profile_update"),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    async def test_fresh_tutoring_schedules_one_card_update_only_after_finish(self):
        await main.tutor_endpoint(FakeRequest({}))
        self.mocks["schedule"].assert_not_called()

        self.assertTrue(review.finish(TRANSCRIPT.stem))
        self.assertFalse(review.finish(TRANSCRIPT.stem))

        self.mocks["schedule"].assert_called_once_with(TUTORING)

    async def test_card_update_fires_after_the_delay_without_finish(self):
        with mock.patch.object(review, "CARD_DELAY_SEC", 0):
            await main.tutor_endpoint(FakeRequest({}))
            await review._TIMERS[TRANSCRIPT.stem]

        self.mocks["schedule"].assert_called_once_with(TUTORING)
        self.assertFalse(review.finish(TRANSCRIPT.stem))

    async def test_finish_leaves_out_items_the_learner_marked(self):
        tutoring = {
            "corrections": [
                {"said": "a", "better": "I just started", "why": "x"},
                {"said": "b", "better": "I got swamped", "why": "y"},
            ],
            "us_style": [{"said": "s", "korean_way": "k", "natural": "Thanks for jumping on this", "why": "w"}],
        }
        self.mocks["run"].side_effect = lambda path: (dict(tutoring), True)
        await main.tutor_endpoint(FakeRequest({}))
        review.apply_flag(TRANSCRIPT.stem, "correction", "I just started", "misheard")
        review.apply_flag(TRANSCRIPT.stem, "us_style", "Thanks for jumping on this", "known")
        review.apply_flag(TRANSCRIPT.stem, "correction", "I got swamped", "saved")
        review.finish(TRANSCRIPT.stem)

        sent = self.mocks["schedule"].call_args.args[0]
        self.assertEqual([c["better"] for c in sent["corrections"]], ["I got swamped"])
        self.assertEqual(sent["us_style"], [])

    async def test_thinking_gaps_reach_card_update_in_both_modes(self):
        gaps = [{"korean": "x", "english": "I'm swamped", "kind": "framing", "note": "n"}]
        self.mocks["run"].side_effect = lambda path: ({**TUTORING, "thinking_gaps": gaps}, True)
        res = json.loads((await main.tutor_endpoint(FakeRequest({}))).body)

        self.assertEqual(res["stem"], TRANSCRIPT.stem)
        self.finish()
        self.mocks["schedule"].assert_called_once_with({**TUTORING, "thinking_gaps": gaps})
        self.mocks["schedule"].reset_mock()
        main._PROFILE_UPDATED.clear()
        result = {"corrections": [], "thinking_gaps": gaps, "unanswered": ["x"], "lesson_date": "2026-10-13"}
        with mock.patch.object(main, "get_lesson", return_value={"date": "2026-10-13", "sections": []}), \
                mock.patch.object(main, "lesson_text", return_value=""), \
                mock.patch.object(main, "run_teachback", side_effect=lambda *a: (dict(result), True)):
            await main.tutor_endpoint(FakeRequest({"mode": "teachback"}))
        self.finish()
        self.mocks["schedule"].assert_called_once_with({"corrections": [], "thinking_gaps": gaps})

    async def test_cached_result_does_not_update_card(self):
        await main.tutor_endpoint(FakeRequest({}))
        await main.tutor_endpoint(FakeRequest({}))

        self.assertEqual(self.mocks["run"].call_count, 1)
        self.finish()
        self.mocks["schedule"].assert_called_once()

    async def test_same_call_analyzed_again_after_cache_expiry_updates_card_once(self):
        await main.tutor_endpoint(FakeRequest({}))
        main._TUTOR_CACHE.clear()
        await main.tutor_endpoint(FakeRequest({}))

        self.assertEqual(self.mocks["run"].call_count, 2)
        self.finish()
        self.mocks["schedule"].assert_called_once()

    async def test_response_carries_cost_object_and_card_update_does_not(self):
        self.mocks["run"].side_effect = lambda path: ({**TUTORING, "cost_usd": 0.002}, True)
        with mock.patch.object(main, "live_cost_of", return_value=0.01):
            res = await main.tutor_endpoint(FakeRequest({}))

        self.assertEqual(json.loads(res.body)["cost"], {"live": 0.01, "tutoring": 0.002, "total": 0.012})
        self.finish()
        self.mocks["schedule"].assert_called_once_with(TUTORING)

    async def test_cost_total_is_null_when_nothing_was_measured(self):
        with mock.patch.object(main, "live_cost_of", return_value=None):
            res = await main.tutor_endpoint(FakeRequest({}))

        self.assertEqual(json.loads(res.body)["cost"], {"live": None, "tutoring": None, "total": None})

    async def _teachback(self):
        result = {"corrections": TUTORING["corrections"], "unanswered": ["x"], "lesson_date": "2026-10-13"}
        with mock.patch.object(main, "get_lesson", return_value={"date": "2026-10-13", "sections": []}), \
                mock.patch.object(main, "lesson_text", return_value=""), \
                mock.patch.object(main, "run_teachback", side_effect=lambda *a: (dict(result), True)):
            await main.tutor_endpoint(FakeRequest({"mode": "teachback"}))

    async def test_fresh_teachback_schedules_one_card_update_without_non_english_keys(self):
        await self._teachback()
        self.finish()

        self.mocks["schedule"].assert_called_once_with({"corrections": TUTORING["corrections"]})

    async def test_teachback_again_after_cache_expiry_updates_card_once(self):
        await self._teachback()
        main._TUTOR_CACHE.clear()
        await self._teachback()
        self.finish()

        self.mocks["schedule"].assert_called_once()


    async def test_every_success_branch_returns_stem(self):
        first = json.loads((await main.tutor_endpoint(FakeRequest({}))).body)
        cached = json.loads((await main.tutor_endpoint(FakeRequest({}))).body)
        self.assertEqual(self.mocks["run"].call_count, 1)
        self.assertEqual(first["stem"], TRANSCRIPT.stem)
        self.assertEqual(cached["stem"], TRANSCRIPT.stem)
        self.finish()
        self.mocks["schedule"].assert_called_once_with(TUTORING)

    async def test_error_after_path_known_carries_stem(self):
        for exc, status in [(main.TutoringAnalysisError("빈 결과"), 502), (RuntimeError("boom"), 500)]:
            main._TUTOR_CACHE.clear()
            self.mocks["run"].side_effect = exc
            res = await main.tutor_endpoint(FakeRequest({}))
            self.assertEqual(res.status_code, status)
            body = json.loads(res.body)
            self.assertEqual(body["stem"], TRANSCRIPT.stem)
            self.assertTrue(body["detail"])
        self.mocks["schedule"].assert_not_called()

    async def test_latency_in_body_is_saved_for_success_and_error_with_stem(self):
        latency = {"turns_ms": [900], "first_audio_ms": 1500, "cutoffs": 1}
        with mock.patch("server.history.save_latency") as save:
            await main.tutor_endpoint(FakeRequest({"latency": latency}))
            save.assert_called_once_with(TRANSCRIPT.stem, latency)
        main._TUTOR_CACHE.clear()
        self.mocks["run"].side_effect = main.TutoringAnalysisError("빈 결과")
        with mock.patch("server.history.save_latency") as save:
            res = await main.tutor_endpoint(FakeRequest({"latency": latency}))
            self.assertEqual(res.status_code, 502)
            save.assert_called_once_with(TRANSCRIPT.stem, latency)

    async def test_bad_or_failing_latency_never_fails_the_tutor_request(self):
        for latency, exc in [({"turns_ms": "x"}, ValueError("bad")), ({"turns_ms": []}, FileNotFoundError("none")), ("oops", None), (5, None)]:
            main._TUTOR_CACHE.clear()
            with mock.patch("server.history.save_latency", side_effect=exc) as save:
                res = await main.tutor_endpoint(FakeRequest({"latency": latency}))
            self.assertEqual(res.status_code, 200, latency)
            self.assertEqual(json.loads(res.body)["stem"], TRANSCRIPT.stem)
            if not isinstance(latency, dict):
                save.assert_not_called()

    async def test_no_latency_in_body_saves_nothing(self):
        with mock.patch("server.history.save_latency") as save:
            await main.tutor_endpoint(FakeRequest({}))
        save.assert_not_called()

    async def test_error_before_path_known_has_no_stem(self):
        self.mocks["resolve"].side_effect = FileNotFoundError("저장된 통화 기록이 없습니다")
        with self.assertRaises(main.HTTPException) as ctx:
            await main.tutor_endpoint(FakeRequest({}))
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_teachback_returns_stem_fresh_and_cached(self):
        result = {"corrections": [], "lesson_date": "2026-10-13"}
        with mock.patch.object(main, "get_lesson", return_value={"date": "2026-10-13", "sections": []}), \
                mock.patch.object(main, "lesson_text", return_value=""), \
                mock.patch.object(main, "run_teachback", side_effect=lambda *a: (dict(result), True)):
            first = json.loads((await main.tutor_endpoint(FakeRequest({"mode": "teachback"}))).body)
            cached = json.loads((await main.tutor_endpoint(FakeRequest({"mode": "teachback"}))).body)
        self.assertEqual(first["stem"], TRANSCRIPT.stem)
        self.assertEqual(cached["stem"], TRANSCRIPT.stem)


class ReadglossWiringTest(unittest.IsolatedAsyncioTestCase):
    setUp = TutorEndpointWiringTest.setUp

    async def test_tutoring_never_pushes_to_readgloss(self):
        first = await main.tutor_endpoint(FakeRequest({}))
        main._TUTOR_CACHE.clear()
        await main.tutor_endpoint(FakeRequest({}))
        review.finish(TRANSCRIPT.stem)

        self.mocks["bridge"].assert_not_called()
        self.assertIn(b'"readgloss":null', first.body)

    async def test_teachback_never_pushes_to_readgloss_and_waits_for_finish(self):
        result = {"corrections": TUTORING["corrections"], "lesson_date": "2026-10-13"}
        with mock.patch.object(main, "get_lesson", return_value={"date": "2026-10-13", "sections": []}), \
                mock.patch.object(main, "lesson_text", return_value=""), \
                mock.patch.object(main, "run_teachback", side_effect=lambda *a: (dict(result), True)):
            res = await main.tutor_endpoint(FakeRequest({"mode": "teachback"}))

        self.assertIn(b'"readgloss":null', res.body)
        self.mocks["bridge"].assert_not_called()
        self.mocks["schedule"].assert_not_called()
        self.assertTrue(review.finish(TRANSCRIPT.stem))

    async def test_card_update_gets_no_readgloss_fields(self):
        await main.tutor_endpoint(FakeRequest({}))
        review.finish(TRANSCRIPT.stem)

        sent = self.mocks["schedule"].call_args.args[0]
        self.assertNotIn("readgloss", sent)
        self.assertNotIn("practice_used", sent)

    async def test_practice_words_used_in_transcript_are_reported(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"TUTORING_DIR": tmp}):
            path = Path(tmp) / "2026-10-20-090000.md"
            path.write_text("**Partner:** Mitigate it?\n**Me:** We mitigated the risk.\n", encoding="utf-8")
            self.mocks["resolve"].return_value = path
            res = await main.tutor_endpoint(FakeRequest({"practice_words": ["mitigate", "haphazard", "Bad Word", 3]}))

        self.assertIn(b'"practice_used":["mitigate"]', res.body)


class IceCandidateTest(unittest.IsolatedAsyncioTestCase):
    def request(self, pc_id, candidate):
        from pipecat.transports.smallwebrtc.request_handler import IceCandidate, SmallWebRTCPatchRequest

        return SmallWebRTCPatchRequest(pc_id=pc_id, candidates=[IceCandidate(candidate=candidate, sdp_mid="0", sdp_mline_index=0)])

    async def test_malformed_candidate_gives_400(self):
        from fastapi import HTTPException

        with mock.patch.dict(main._webrtc._pcs_map, {"pc1": mock.AsyncMock()}):
            with self.assertRaises(HTTPException) as ctx:
                await main.ice_candidate(self.request("pc1", "candidate:garbage"))

        self.assertEqual(ctx.exception.status_code, 400)

    async def test_unknown_pc_id_stays_404(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await main.ice_candidate(self.request("nope", "candidate:1 1 udp 1 127.0.0.1 9 typ host"))

        self.assertEqual(ctx.exception.status_code, 404)


EMPTY_PROFILE = {
    "load_failed": False,
    "brief": "",
    "pron": None,
    "interests": [],
    "updated": None,
    "weak_points": [],
    "next_goal": "",
    "practice_words": [],
    "wordbook": {"words": [], "phrases": []},
    "native_expressions": [],
}
EMPTY_BOOK = {"words": [], "phrases": []}

PRON_RESULT = {
    "date": "2026-10-20",
    "created_at": "2026-10-20T09:00:00+09:00",
    "contrasts": [
        {
            "contrast": "can_cant",
            "label": "can / can't",
            "total": 4,
            "as_target": 1,
            "as_other": 3,
            "unclear": 0,
            "misheard": [{"target": "can't", "heard_text": "I can go."}] * 3,
            "tip": "x",
        },
        {"contrast": "l_r", "label": "l / r", "total": 4, "as_target": 4, "as_other": 0, "unclear": 0, "misheard": [], "tip": "x"},
    ],
    "cost_usd": None,
}


class LearnerProfileEndpointTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        patcher = mock.patch.object(main, "bridge_lists", return_value=([], EMPTY_BOOK))
        self.practice = patcher.start()
        self.addCleanup(patcher.stop)
        pron_patcher = mock.patch.object(pron, "latest_result", return_value=None)
        self.pron_latest = pron_patcher.start()
        self.addCleanup(pron_patcher.stop)
        native_patcher = mock.patch.object(main.native_expr, "load", return_value=[])
        self.native_load = native_patcher.start()
        self.addCleanup(native_patcher.stop)
        learner_patcher = mock.patch.object(main.native_expr, "recent_learner_text", return_value="")
        learner_patcher.start()
        self.addCleanup(learner_patcher.stop)

    async def test_native_expressions_are_picked_from_the_list(self):
        entry = main.native_expr.clean_entry(
            {
                "expression": "figure out",
                "kind": "phrasal_verb",
                "meaning_ko": "알아내다",
                "register": "casual",
                "per_million": 100,
                "clips": [{"video_id": "v", "start": 1, "end": 3, "text": "we figure out"}],
            }
        )
        self.native_load.return_value = [entry]
        with mock.patch.object(main, "load_profile", return_value=None), \
                mock.patch.dict("os.environ", {"KNOWN_EXPRESSIONS_PATH": "/nonexistent/known.json"}):
            body = await main.learner_profile_endpoint()

        self.assertEqual(body["native_expressions"], [{"phrase": "figure out", "meaning": "알아내다"}])

    async def test_slow_bridge_does_not_hold_the_home_screen(self):
        import threading

        release = threading.Event()
        self.addCleanup(release.set)
        self.practice.side_effect = lambda: release.wait(5) and ([], EMPTY_BOOK)
        with mock.patch.object(main, "PRACTICE_DEADLINE_SEC", 0.1), \
                mock.patch.object(main, "load_profile", return_value=None):
            body = await main.learner_profile_endpoint()

        self.assertEqual(body["practice_words"], [])
        self.assertEqual(body["wordbook"], EMPTY_BOOK)

    async def test_wordbook_for_friends_is_passed_through(self):
        book = {"words": [{"lemma": "mitigate", "gloss": "완화하다"}], "phrases": [{"text": "short shift", "gloss": "짧은 근무"}]}
        self.practice.return_value = ([], book)
        with mock.patch.object(main, "load_profile", return_value=None):
            body = await main.learner_profile_endpoint()

        self.assertEqual(body["wordbook"], book)

    async def test_readgloss_practice_words_are_passed_through(self):
        self.practice.return_value = ([{"lemma": "mitigate", "gloss": "완화하다", "source": "lookup"}], EMPTY_BOOK)
        with mock.patch.object(main, "load_profile", return_value=None):
            body = await main.learner_profile_endpoint()

        self.assertEqual(body["practice_words"], [{"lemma": "mitigate", "gloss": "완화하다", "source": "lookup"}])

    async def test_broken_card_gives_empty_brief_marked_as_failed(self):
        with mock.patch.object(main, "load_profile", side_effect=main.ProfileError("broken")):
            self.assertEqual(await main.learner_profile_endpoint(), {**EMPTY_PROFILE, "load_failed": True})

    async def test_missing_card_gives_empty_brief(self):
        with mock.patch.object(main, "load_profile", return_value=None):
            self.assertEqual(await main.learner_profile_endpoint(), EMPTY_PROFILE)

    async def test_card_gives_top_three_weak_points_for_home_screen(self):
        points = [
            {"pattern": f"p{i}", "count": 1, "last_seen": "2026-10-20", "example": f"e{i}", "misses": 0}
            for i in range(4)
        ]
        card = {
            "updated": "2026-10-20T09:00:00+09:00",
            "level": {"cefr": "B1.2", "actfl": "Intermediate High", "source": "t"},
            "weak_points": points,
            "fixed_points": [],
            "phrases": [],
            "pragmatics": [],
            "interests": [],
            "next_goal": "Ask with do.",
        }
        with mock.patch.object(main, "load_profile", return_value=card):
            body = await main.learner_profile_endpoint()

        self.assertEqual(body["weak_points"], [{"pattern": f"p{i}", "example": f"e{i}"} for i in range(3)])
        self.assertEqual(body["next_goal"], "Ask with do.")
        self.assertIn("p0", body["brief"])


    async def test_interests_come_from_the_card(self):
        card = {
            "updated": "2026-10-20T09:00:00+09:00",
            "level": {"cefr": "", "actfl": "", "source": ""},
            "weak_points": [],
            "fixed_points": [],
            "phrases": [],
            "pragmatics": [],
            "interests": ["hiking", "security"],
            "next_goal": "",
        }
        with mock.patch.object(main, "load_profile", return_value=card):
            body = await main.learner_profile_endpoint()

        self.assertEqual(body["interests"], ["hiking", "security"])

    async def test_pron_result_adds_brief_lines_and_weak_summary(self):
        self.pron_latest.return_value = PRON_RESULT
        with mock.patch.object(main, "load_profile", return_value=None):
            body = await main.learner_profile_endpoint()

        self.assertTrue(body["brief"].startswith("Pronunciation check (reading test 2026-10-20)"))
        self.assertEqual(
            body["pron"],
            {"date": "2026-10-20", "weak": [{"label": "can / can't", "as_other": 3, "unclear": 0, "total": 4}]},
        )

    async def test_pron_brief_comes_before_the_card_brief(self):
        self.pron_latest.return_value = PRON_RESULT
        card = {
            "updated": "2026-10-20T09:00:00+09:00",
            "level": {"cefr": "B1.2", "actfl": "", "source": ""},
            "weak_points": [],
            "fixed_points": [],
            "phrases": [],
            "pragmatics": [],
            "interests": [],
            "next_goal": "",
        }
        with mock.patch.object(main, "load_profile", return_value=card):
            body = await main.learner_profile_endpoint()

        self.assertTrue(body["brief"].startswith("Pronunciation check"))
        self.assertIn("\nLevel: B1.2.", body["brief"])


class PhraseEndpointsTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(main.app)

    def test_save_sends_normalized_text_and_answers_saved(self):
        with mock.patch.object(main, "save_phrase", return_value=True) as save:
            res = self.client.post("/api/phrase/save", json={"text": "  I can't   make it. ", "translation": " 못 가요. "})

        self.assertEqual((res.status_code, res.json()), (200, {"saved": True}))
        save.assert_called_once_with("I can't make it.", "못 가요.")

    def test_save_translation_may_be_empty_or_missing(self):
        with mock.patch.object(main, "save_phrase", return_value=True) as save:
            self.assertEqual(self.client.post("/api/phrase/save", json={"text": "Circle back", "translation": ""}).status_code, 200)
            self.assertEqual(self.client.post("/api/phrase/save", json={"text": "Circle back"}).status_code, 200)

        self.assertEqual(save.call_count, 2)

    def test_save_rejects_bad_fields_and_non_json(self):
        bad = [
            {"text": "a"},
            {"text": " 12 34 "},
            {"text": "x" * 1001},
            {"text": 5},
            {"translation": "x"},
            {"text": "Circle back", "translation": "x" * 301},
            {"text": "Circle back", "translation": 3},
        ]
        with mock.patch.object(main, "save_phrase", return_value=True) as save:
            for body in bad:
                with self.subTest(body=str(body)[:40]):
                    self.assertEqual(self.client.post("/api/phrase/save", json=body).status_code, 400)
            res = self.client.post("/api/phrase/save", content='{"text": "Circle back"}', headers={"content-type": "text/plain"})
            self.assertEqual(res.status_code, 415)
            self.assertEqual(self.client.post("/api/phrase/save", json={"text": "x" * 1000}).status_code, 200)
            self.assertEqual(self.client.post("/api/phrase/save", json={"text": "ab"}).status_code, 200)

        self.assertEqual(save.call_count, 2)

    def test_save_is_503_with_korean_detail_when_bridge_is_off(self):
        with mock.patch.object(main, "save_phrase", return_value=False):
            res = self.client.post("/api/phrase/save", json={"text": "Circle back"})

        self.assertEqual((res.status_code, res.json()), (503, {"detail": "readgloss가 꺼져 있어 저장하지 못했어요."}))

    def test_status_compares_normalized_text_in_order(self):
        with mock.patch.object(main, "stored_phrase_keys", return_value={"circle back later"}):
            res = self.client.post("/api/phrase/status", json={"texts": ["Circle  BACK later", "Something else", ""]})

        self.assertEqual((res.status_code, res.json()), (200, {"saved": [True, False, False]}))

    def test_status_rejects_bad_lists_and_is_503_when_bridge_is_off(self):
        with mock.patch.object(main, "stored_phrase_keys", return_value=None):
            self.assertEqual(self.client.post("/api/phrase/status", json={"texts": ["a b"]}).status_code, 503)
            for body in ({"texts": "x"}, {"texts": [1]}, {"texts": ["x"] * 41}, {}):
                with self.subTest(body=str(body)[:30]):
                    self.assertEqual(self.client.post("/api/phrase/status", json=body).status_code, 400)
            res = self.client.post("/api/phrase/status", content="{}", headers={"content-type": "text/plain"})
            self.assertEqual(res.status_code, 415)


class WordEndpointsTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(main.app)

    def post(self, path, body):
        return self.client.post(path, json=body)

    def test_lookup_returns_the_compact_dict(self):
        compact = {"word": "leverage", "lemma": "leverage", "gloss": "영향력", "senses": ["영향력"], "pos": "명사"}
        with mock.patch.object(main, "lookup_word", return_value=compact) as lookup:
            res = self.post("/api/word", {"word": "leverage"})

        self.assertEqual((res.status_code, res.json()), (200, compact))
        lookup.assert_called_once_with("leverage")

    def test_lookup_rejects_anything_but_one_english_word(self):
        with mock.patch.object(main, "lookup_word") as lookup:
            for body in ({"word": "two words"}, {"word": ""}, {"word": "123"}, {"word": 5}, {}, {"word": "a" * 65}):
                with self.subTest(body=str(body)):
                    self.assertEqual(self.post("/api/word", body).status_code, 400)
            self.assertEqual(self.client.post("/api/word", json=["leverage"]).status_code, 400)

        lookup.assert_not_called()

    def test_lookup_is_503_with_korean_detail_when_bridge_is_off(self):
        with mock.patch.object(main, "lookup_word", return_value=None):
            res = self.post("/api/word", {"word": "leverage"})

        self.assertEqual((res.status_code, res.json()), (503, {"detail": "readgloss가 꺼져 있어 뜻을 찾지 못했어요."}))

    def test_word_endpoints_are_json_only(self):
        for path in ("/api/word", "/api/word/save"):
            res = self.client.post(path, content='{"word": "leverage"}', headers={"content-type": "text/plain"})
            self.assertEqual(res.status_code, 415)

    def test_save_passes_normalized_values_and_answers_saved(self):
        body = {"word": "Leverages", "lemma": "Leverage", "gloss": "활용하다", "sentence": "We leverage it."}
        with mock.patch.object(main, "save_word", return_value=True) as save:
            res = self.post("/api/word/save", body)

        self.assertEqual((res.status_code, res.json()), (200, {"saved": True}))
        save.assert_called_once_with("leverage", "Leverages", "활용하다", "We leverage it.")

    def test_save_rejects_bad_fields(self):
        good = {"word": "leverage", "lemma": "leverage", "gloss": "활용", "sentence": "x"}
        bad = [
            {**good, "word": "two words"},
            {**good, "lemma": "two words"},
            {**good, "lemma": 3},
            {**good, "sentence": "x" * 1001},
            {**good, "gloss": "x" * 201},
            {**good, "gloss": 7},
        ]
        with mock.patch.object(main, "save_word", return_value=True) as save:
            for body in bad:
                with self.subTest(body=str(body)[:50]):
                    self.assertEqual(self.post("/api/word/save", body).status_code, 400)
            self.assertEqual(self.post("/api/word/save", {**good, "sentence": "x" * 1000}).status_code, 200)

        self.assertEqual(save.call_count, 1)

    def test_save_is_503_when_bridge_is_off(self):
        with mock.patch.object(main, "save_word", return_value=False):
            res = self.post("/api/word/save", {"word": "leverage", "lemma": "leverage", "gloss": "", "sentence": ""})

        self.assertEqual(res.status_code, 503)


class LatencyEndpointTest(unittest.TestCase):
    URL = "/api/calls/2026-10-20-120000/latency"

    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(main.app)

    def test_passes_body_to_save_and_maps_errors(self):
        body = {"turns_ms": [900], "first_audio_ms": 2000}
        with mock.patch("server.history.save_latency") as save:
            self.assertEqual(self.client.post(self.URL, json=body).status_code, 200)
            save.assert_called_once_with("2026-10-20-120000", body)
        with mock.patch("server.history.save_latency", side_effect=ValueError("bad")):
            self.assertEqual(self.client.post(self.URL, json=body).status_code, 400)
        with mock.patch("server.history.save_latency", side_effect=FileNotFoundError("none")):
            self.assertEqual(self.client.post(self.URL, json=body).status_code, 404)

    def test_non_json_body_is_rejected_before_saving(self):
        with mock.patch("server.history.save_latency") as save:
            res = self.client.post(self.URL, content="x", headers={"content-type": "text/plain"})
        self.assertEqual(res.status_code, 415)
        save.assert_not_called()


class CultureEndpointTest(unittest.TestCase):
    STEM = "2026-10-20-120000"

    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(main.app)

    def get(self, tutoring, available=True, search=None):
        call = {"stem": self.STEM, "tutoring": tutoring}
        with mock.patch.object(main, "load_call", return_value=call), mock.patch.object(
            main.culturedb, "available", return_value=available
        ), mock.patch.object(main.culturedb, "search", return_value=search or {"blend": [], "bank": []}) as s:
            return self.client.get(f"/api/calls/{self.STEM}/culture"), s

    def test_ok_extracts_terms_and_returns_hits(self):
        tutoring = {
            "clip_query": "the coffee at a cafe",
            "vocab": [{"word": "latte"}, {"word": "coffee"}],
            "thinking_gaps": [{"korean": "a", "english": "coffee"}],
        }
        hits = {
            "blend": [{"id": "b", "question": "What coffee do people drink?", "korea": [], "us": []}],
            "bank": [{"country": "US", "topic": "coffee", "context": "cafe", "text": "x"}],
        }
        res, s = self.get(tutoring, search=hits)
        body = res.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["terms"], ["coffee", "cafe", "latte"])  # 폴백 단어는 최대 3개
        self.assertEqual((body["blend"], body["bank"]), (hits["blend"], hits["bank"]))
        self.assertEqual(body["attribution"], main.culturedb.ATTRIBUTION)
        s.assert_called_once_with(["coffee", "cafe", "latte"], main.CULTURE_CANDIDATE_BLEND, main.CULTURE_CANDIDATE_BANK)

    def test_off_topic_notes_are_dropped_and_the_block_is_empty(self):
        tutoring = {"topic_keywords": ["meeting", "deadline"], "clip_query": "coworkers at the beach"}
        hits = {
            "blend": [{"id": "b", "question": "What do people wear at the beach?", "korea": [], "us": []}],
            "bank": [{"country": "US", "topic": "swimwear", "context": "beach", "text": "Americans wear swimwear at the beach."}],
        }
        res, _ = self.get(tutoring, search=hits)
        body = res.json()
        self.assertEqual((body["status"], body["blend"], body["bank"]), ("ok", [], []))

    def test_terms_capped_at_six(self):
        res, _ = self.get({"topic_keywords": ["alpha one", "bravo two", "charlie three", "delta four", "echo five", "foxtrot six", "golf seven"]})
        self.assertEqual(len(res.json()["terms"]), 6)
        res, _ = self.get({"clip_query": "alpha bravo charlie delta echo foxtrot golf hotel india juliet"})
        self.assertEqual(res.json()["terms"], ["alpha", "bravo", "charlie"])  # 폴백 단어만이면 3개

    def test_terms_prefer_topic_keywords_then_fill(self):
        tutoring = {
            "topic_keywords": ["Kitchen", "cutting board", "busy week"],
            "clip_query": "coworkers talk busy week",
            "vocab": [{"word": "swamped"}],
            "thinking_gaps": [{"english": "cutting board"}],
        }
        # 이미 구절에 들어 있는 단어(busy, cutting)는 채우지 않는다
        self.assertEqual(main._culture_terms(tutoring), ["kitchen", "cutting board", "busy week", "swamped"])

    def test_generic_words_dropped(self):
        tutoring = {
            "topic_keywords": ["talk", "coffee"],
            "clip_query": "coworkers talk people place thing day time week today really good great nice lot cafe",
        }
        self.assertEqual(main._culture_terms(tutoring), ["coffee", "cafe"])

    def test_old_call_without_topic_keywords(self):
        self.assertEqual(main._culture_terms({"clip_query": "the coffee at a cafe"}), ["coffee", "cafe"])
        self.assertEqual(main._culture_terms({"topic_keywords": "junk", "clip_query": "coffee"}), ["coffee"])

    def test_no_db(self):
        res, s = self.get({"clip_query": "coffee"}, available=False)
        self.assertEqual(res.json()["status"], "no_db")
        s.assert_not_called()

    def test_no_terms(self):
        res, s = self.get({"clip_query": "to be"})
        body = res.json()
        self.assertEqual((body["status"], body["terms"], body["blend"], body["bank"]), ("no_terms", [], [], []))
        s.assert_not_called()

    def test_bad_stem_400_and_unknown_404(self):
        with mock.patch.object(main, "load_call", side_effect=ValueError("bad")):
            self.assertEqual(self.client.get("/api/calls/x/culture").status_code, 400)
        with mock.patch.object(main, "load_call", side_effect=FileNotFoundError("none")):
            self.assertEqual(self.client.get(f"/api/calls/{self.STEM}/culture").status_code, 404)


class ClipsAndTtsEndpointsTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        self.client = TestClient(main.app)

    def clips(self, tutoring, **patch):
        call = {"stem": "2026-10-20-120000", "tutoring": tutoring}
        with mock.patch.object(main, "load_call", return_value=call), mock.patch.object(
            main.clipdb, "available", return_value=False
        ), mock.patch.object(main.youtube, "clips_for_call", **patch) as clips:
            return self.client.get("/api/calls/2026-10-20-120000/clips"), clips

    def db_clips(self, tutoring, hits, **patch):
        """자막 DB 검색을 가짜로 바꾼다. hits: 문구 -> 검색 결과 목록."""
        call = {"stem": "2026-10-20-120000", "tutoring": tutoring}
        calls = []

        def fake_search(phrase, limit=5, genre=None, path=None):
            calls.append((phrase, limit))
            return hits.get(phrase, [])

        with mock.patch.object(main, "load_call", return_value=call), mock.patch.object(
            main.clipdb, "available", return_value=True
        ), mock.patch.object(main.clipdb, "search", side_effect=fake_search), mock.patch.object(
            main.youtube, "clips_for_call", **patch
        ) as clips:
            return self.client.get("/api/calls/2026-10-20-120000/clips"), clips, calls

    @staticmethod
    def hit(vid, text, start=12.7):
        return {"video_id": vid, "title": f"T{vid}", "channel": "Ch", "genre": "g", "start": start, "end": start + 3, "text": text}

    def test_clips_db_first_with_three_skips_search(self):
        tutoring = {
            "clip_query": "small talk",
            "vocab": [{"word": "a"}, {"word": "wrap up"}, {"word": "touch base"}],
            "retry": {"target_phrases": ["heads up"]},
            "corrections": [{"better": "I would like to reschedule"}, {"better": "one two three four five six seven"}],
        }
        hits = {
            "wrap up": [self.hit("v1", "let's wrap up"), self.hit("v2", "wrap up now")],
            "touch base": [self.hit("v1", "dup video"), self.hit("v3", "touch base later")],
            "heads up": [self.hit("v4", "a heads up")],
        }
        res, clips, calls = self.db_clips(tutoring, hits)
        body = res.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["source"], "db")
        self.assertEqual(body["query"], "heads up, wrap up, touch base")
        self.assertEqual([c["id"] for c in body["clips"]], ["v4", "v1", "v3", "v2"])
        self.assertEqual(
            body["clips"][1],
            {
                "id": "v1", "title": "Tv1", "channel": "Ch", "thumbnail": "https://i.ytimg.com/vi/v1/mqdefault.jpg",
                "start": 12, "text": "let's wrap up", "phrase": "wrap up", "source": "db",
            },
        )
        clips.assert_not_called()
        self.assertEqual([p for p, _ in calls], ["heads up", "I would like to reschedule", "wrap up", "touch base"])
        self.assertTrue(all(limit == 2 for _, limit in calls))

    def test_clip_phrases_order_phrases_before_words(self):
        tutoring = {
            "vocab": [{"word": "leverage"}, {"word": "wrap up"}],
            "retry": {"target_phrases": ["heads up"]},
            "corrections": [{"better": "Could you send it"}, {"better": "Yes"}],
        }
        self.assertEqual(main._clip_phrases(tutoring), ["heads up", "Could you send it", "leverage", "wrap up"])

    def test_clips_db_round_robin_one_per_phrase_first(self):
        hits = {
            "heads up": [self.hit("a1", "x"), self.hit("a2", "x")],
            "touch base": [self.hit("b1", "x"), self.hit("b2", "x")],
            "leverage": [self.hit("c1", "x")],
        }
        tutoring = {"retry": {"target_phrases": ["heads up", "touch base"]}, "vocab": [{"word": "leverage"}]}
        res, _, _ = self.db_clips(tutoring, hits)
        self.assertEqual([c["id"] for c in res.json()["clips"]], ["a1", "b1", "c1", "a2", "b2"])

    def test_clip_query_normalized_before_search(self):
        for raw, expected in [
            ("Anna's café trip, to Seoul!", "Anna's caf trip to Seoul"),
            ("one", ""),
            ("a b c d e f g h i j k", ""),
            ("한국어 only", ""),
            ("x" * 120, ""),
        ]:
            self.assertEqual(main.normalize_clip_query(raw), expected, raw)
        self.assertLessEqual(len(main.normalize_clip_query(" ".join(["abcdefghij"] * 9))), 100)
        res, clips = self.clips({"clip_query": "small talk <script> now"}, return_value=[{"id": "a"}])
        clips.assert_called_once_with("2026-10-20-120000", "small talk script now")

    def test_clips_db_caps_at_five(self):
        hits = {f"w{i}": [self.hit(f"v{i}", "x")] for i in range(8)}
        res, _, calls = self.db_clips({"vocab": [{"word": f"w{i}"} for i in range(8)]}, hits)
        self.assertEqual(len(res.json()["clips"]), 5)
        self.assertEqual(len(calls), 5)

    def test_clips_db_few_fills_from_search(self):
        hits = {"wrap up": [self.hit("v1", "wrap up")]}
        res, clips, _ = self.db_clips(
            {"clip_query": "small talk", "vocab": [{"word": "wrap up"}]},
            hits,
            return_value=[{"id": "v1", "title": "dup"}, {"id": "s2", "title": "S"}],
        )
        body = res.json()
        self.assertEqual((body["status"], body["source"], body["query"]), ("ok", "mixed", "small talk"))
        self.assertEqual([(c["id"], c["source"]) for c in body["clips"]], [("v1", "db"), ("s2", "search")])

    def test_clips_db_few_and_search_fails_keeps_db(self):
        hits = {"wrap up": [self.hit("v1", "wrap up")]}
        res, _, _ = self.db_clips(
            {"clip_query": "small talk", "vocab": [{"word": "wrap up"}]}, hits, side_effect=main.youtube.YouTubeKeyMissing("x")
        )
        body = res.json()
        self.assertEqual((body["status"], body["source"], len(body["clips"])), ("ok", "db", 1))

    def test_clips_db_empty_no_query(self):
        res, _, _ = self.db_clips({"vocab": [{"word": "zzz"}]}, {})
        self.assertEqual(res.json(), {"query": "", "clips": [], "status": "no_query"})

    def test_clips_ok(self):
        res, clips = self.clips({"clip_query": " small talk "}, return_value=[{"id": "a"}])
        self.assertEqual(
            res.json(),
            {"query": "small talk", "clips": [{"id": "a", "source": "search"}], "status": "ok", "source": "search"},
        )
        clips.assert_called_once_with("2026-10-20-120000", "small talk")

    def test_clips_no_query_skips_search(self):
        for tutoring in (None, {}, {"clip_query": "  "}):
            res, clips = self.clips(tutoring)
            self.assertEqual((res.status_code, res.json()), (200, {"query": "", "clips": [], "status": "no_query"}))
            clips.assert_not_called()

    def test_clips_no_key(self):
        res, _ = self.clips({"clip_query": "small talk"}, side_effect=main.youtube.YouTubeKeyMissing("x"))
        self.assertEqual((res.status_code, res.json()), (200, {"query": "small talk", "clips": [], "status": "no_key"}))

    def test_clips_search_error_is_200_error(self):
        res, _ = self.clips({"clip_query": "small talk"}, side_effect=main.youtube.YouTubeQuotaError("quota"))
        self.assertEqual((res.status_code, res.json()), (200, {"query": "small talk", "clips": [], "status": "error"}))

    def test_clips_bad_and_unknown_stem(self):
        with mock.patch.object(main, "load_call", side_effect=ValueError("bad")):
            self.assertEqual(self.client.get("/api/calls/zz/clips").status_code, 400)
        with mock.patch.object(main, "load_call", side_effect=FileNotFoundError("nope")):
            self.assertEqual(self.client.get("/api/calls/2026-10-20-120000/clips").status_code, 404)

    def test_tts_returns_wav(self):
        with mock.patch.object(main.tts, "synthesize", return_value=b"RIFFxx") as syn:
            res = self.client.post("/api/tts", json={"text": "Hi there.", "voice": "Leda"})
        self.assertEqual((res.status_code, res.headers["content-type"], res.content), (200, "audio/wav", b"RIFFxx"))
        syn.assert_called_once_with("Hi there.", "Leda")

    def test_tts_rejects_bad_input(self):
        with mock.patch.object(main.tts, "synthesize") as syn:
            res = self.client.post("/api/tts", content="{}", headers={"content-type": "text/plain"})
            self.assertEqual(res.status_code, 415)
            for body in ({}, {"text": 1, "voice": "Leda"}, {"text": "", "voice": "Leda"}, {"text": "x" * 501, "voice": "Leda"}, {"text": "Hi", "voice": "../x"}):
                with self.subTest(body=str(body)[:30]):
                    self.assertEqual(self.client.post("/api/tts", json=body).status_code, 400)
        syn.assert_not_called()

    def test_tts_rejects_unknown_voice_without_model_call(self):
        with mock.patch.object(main.tts, "synthesize") as syn:
            for voice in ("Nobody", "kore", "Puck"):
                res = self.client.post("/api/tts", json={"text": "Hi", "voice": voice})
                self.assertEqual(res.status_code, 400, voice)
            syn.assert_not_called()
        for voice in ("Kore", "Leda", "Charon", "Iapetus", "Sulafat", "Fenrir", "Zephyr", "Achird"):
            with mock.patch.object(main.tts, "synthesize", return_value=b"RIFFxx"):
                self.assertEqual(self.client.post("/api/tts", json={"text": "Hi", "voice": voice}).status_code, 200)

    def test_tts_model_failure_is_502(self):
        with mock.patch.object(main.tts, "synthesize", side_effect=main.tts.TTSError("boom")):
            res = self.client.post("/api/tts", json={"text": "Hi", "voice": "Leda"})
        self.assertEqual(res.status_code, 502)


class PartnerMemoryWiringTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._TUTOR_CACHE.clear()
        main._PROFILE_UPDATED.clear()
        isolate_review_state(self)
        patches = {
            "resolve": mock.patch.object(main, "_wait_and_resolve_transcript", return_value=TRANSCRIPT),
            "run": mock.patch.object(main, "run_tutoring", side_effect=lambda path: (dict(TUTORING), True)),
            "profile": mock.patch.object(main, "_schedule_profile_update"),
            "update": mock.patch.object(main.partner_memory, "update", return_value=True),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    async def drain(self):
        while main._background_tasks:
            await asyncio.gather(*list(main._background_tasks))

    async def test_tutor_endpoint_schedules_no_partner_update(self):
        # 기억 갱신은 통화가 끝날 때(call_bot.finish_call 뒤) 걸리고 /api/tutor는 걸지 않는다.
        await main.tutor_endpoint(FakeRequest({}))
        await self.drain()

        self.mocks["update"].assert_not_called()
        self.assertFalse(hasattr(main, "_schedule_partner_memory_update"))

    async def test_teachback_schedules_nothing(self):
        result = {"corrections": [], "thinking_gaps": []}
        with mock.patch.object(main, "get_lesson", return_value={"date": "2026-10-13", "sections": []}), \
                mock.patch.object(main, "lesson_text", return_value=""), \
                mock.patch.object(main, "run_teachback", side_effect=lambda *a: (dict(result), True)):
            await main.tutor_endpoint(FakeRequest({"mode": "teachback"}))
        await self.drain()

        self.mocks["update"].assert_not_called()

    async def test_failed_tutoring_schedules_nothing(self):
        self.mocks["run"].side_effect = main.TutoringAnalysisError("x")
        await main.tutor_endpoint(FakeRequest({}))
        await self.drain()

        self.mocks["update"].assert_not_called()


class ChatEndpointsTest(unittest.TestCase):
    def setUp(self):
        import tempfile

        from fastapi.testclient import TestClient

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict("os.environ", {"CHAT_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        main.chat._INFLIGHT.clear()
        self.client = TestClient(main.app)

    def send(self, pid="priya", **body):
        return self.client.post(f"/api/chat/{pid}", json={"instruction": "be Priya", "message": "hi", **body})

    def test_close_requires_json_body(self):
        self.assertEqual(self.client.post("/api/chat/priya/close").status_code, 415)
        self.assertEqual(
            self.client.post("/api/chat/priya/close", content="{}", headers={"content-type": "text/plain"}).status_code, 415
        )
        res = self.client.post("/api/chat/priya/close", json={})
        self.assertEqual((res.status_code, res.json()), (200, {"status": "nothing"}))

    def test_unknown_and_park_ids_are_400(self):
        for pid in ("park", "nobody"):
            with self.subTest(pid=pid):
                self.assertEqual(self.client.get(f"/api/chat/{pid}").status_code, 400)
                self.assertEqual(self.send(pid).status_code, 400)
                self.assertEqual(self.client.post(f"/api/chat/{pid}/close").status_code, 400)

    def test_send_then_get(self):
        with mock.patch.object(main.chat, "generate_reply", return_value="Hey you!"):
            res = self.send(message="hello")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["reply"], "Hey you!")
        self.assertEqual([m["role"] for m in body["messages"]], ["me", "friend"])
        listed = self.client.get("/api/chat/priya").json()["messages"]
        self.assertEqual([m["text"] for m in listed], ["hello", "Hey you!"])

    def test_bad_bodies_are_400_and_415(self):
        self.assertEqual(self.send(message="").status_code, 400)
        self.assertEqual(self.send(message="x" * 1001).status_code, 400)
        self.assertEqual(self.send(instruction="").status_code, 400)
        self.assertEqual(self.send(instruction="x" * 24001).status_code, 400)
        res = self.client.post("/api/chat/priya", content='{"instruction": "x", "message": "hi"}', headers={"content-type": "text/plain"})
        self.assertEqual(res.status_code, 415)

    def test_model_failure_is_502_and_saves_nothing(self):
        with mock.patch.object(main.chat, "generate_reply", side_effect=RuntimeError("429")):
            res = self.send()
        self.assertEqual(res.status_code, 502)
        self.assertEqual(self.client.get("/api/chat/priya").json(), {"messages": []})


class ShellCacheHeaderTest(unittest.TestCase):
    def test_index_sw_and_manifest_are_no_cache_but_assets_are_not(self):
        import tempfile

        from fastapi.testclient import TestClient

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        dist = Path(tmp.name) / "dist"
        (dist / "assets").mkdir(parents=True)
        for name in ("index.html", "sw.js", "manifest.webmanifest", "assets/app-abc.js"):
            (dist / name).write_text("x", encoding="utf-8")
        old = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, old)
        client = TestClient(main.app)

        for path in ("/", "/sw.js", "/manifest.webmanifest", "/index.html", "/chat/priya"):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).headers.get("cache-control"), "no-cache")
        self.assertNotEqual(client.get("/assets/app-abc.js").headers.get("cache-control"), "no-cache")


class _JsonRequest:
    """main.chat_close를 직접 부를 때 쓰는 JSON 본문({}) 요청."""

    headers = {"content-type": "application/json"}

    async def json(self):
        return {}


class ChatCloseWiringTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.dict("os.environ", {"CHAT_DIR": self.tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        main.chat._INFLIGHT.clear()

    async def drain(self):
        while main._background_tasks:
            await asyncio.gather(*list(main._background_tasks))

    async def test_close_schedules_one_chat_memory_update_over_new_messages(self):
        main.chat.append_messages("priya", [{"role": "me", "text": "I like tea", "at": ""}, {"role": "friend", "text": "Same!", "at": ""}])
        with mock.patch.object(main.partner_memory, "update", return_value=True) as update, mock.patch(
            "server.tutor.make_generate_text", return_value=lambda prompt: "{}"
        ):
            first = await main.chat_close("priya", _JsonRequest())
            await self.drain()
            second = await main.chat_close("priya", _JsonRequest())
            await self.drain()

        self.assertEqual(first, {"status": "scheduled"})
        self.assertEqual(second, {"status": "nothing"})
        update.assert_called_once()
        args, kwargs = update.call_args
        self.assertEqual(args[0], "priya")
        self.assertEqual(args[1], [("me", "I like tea"), ("partner", "Same!")])
        self.assertEqual(kwargs["mode"], "chat")

    async def test_close_during_update_is_nothing_then_one_more_update_covers_only_new_messages(self):
        main.chat.append_messages("priya", [{"role": "me", "text": "first", "at": ""}, {"role": "friend", "text": "ok", "at": ""}])
        calls = []
        overlap = []

        def fake_update(partner_id, turns, generate_text=None, mode="call"):
            calls.append(list(turns))
            if len(calls) == 1:  # 갱신이 도는 중에 새 메시지가 오고 close가 또 온다
                main.chat.append_messages("priya", [{"role": "me", "text": "second", "at": ""}, {"role": "friend", "text": "yes", "at": ""}])
                overlap.append(asyncio.run(main.chat_close("priya", _JsonRequest())))
            return True

        with mock.patch.object(main.partner_memory, "update", side_effect=fake_update), mock.patch(
            "server.tutor.make_generate_text", return_value=lambda prompt: "{}"
        ):
            first = await main.chat_close("priya", _JsonRequest())
            await self.drain()

        self.assertEqual(first, {"status": "scheduled"})
        self.assertEqual(overlap, [{"status": "nothing"}])
        self.assertEqual(calls, [[("me", "first"), ("partner", "ok")], [("me", "second"), ("partner", "yes")]])
        self.assertEqual(main.chat._read_state("priya"), 4)
        self.assertEqual(main.chat._INFLIGHT, {})

    async def test_close_with_no_messages_is_nothing(self):
        with mock.patch.object(main.partner_memory, "update") as update:
            self.assertEqual(await main.chat_close("jake", _JsonRequest()), {"status": "nothing"})
        update.assert_not_called()


if __name__ == "__main__":
    unittest.main()

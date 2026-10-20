import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import main, pron

TRANSCRIPT = Path("/nonexistent/2026-10-20-090000.md")
TUTORING = {"corrections": [{"said": "I just start", "better": "I just started", "why": "x"}]}


class FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class TutorEndpointWiringTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._TUTOR_CACHE.clear()
        main._PROFILE_UPDATED.clear()
        main._READGLOSS_PUSHED.clear()
        patches = {
            "push": mock.patch.object(main, "push_tutoring", return_value=2),
            "resolve": mock.patch.object(main, "_wait_and_resolve_transcript", return_value=TRANSCRIPT),
            "run": mock.patch.object(main, "run_tutoring", side_effect=lambda path: (dict(TUTORING), True)),
            "schedule": mock.patch.object(main, "_schedule_profile_update"),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    async def test_fresh_tutoring_schedules_one_card_update(self):
        await main.tutor_endpoint(FakeRequest({}))

        self.mocks["schedule"].assert_called_once_with(TUTORING)

    async def test_cached_result_does_not_update_card(self):
        await main.tutor_endpoint(FakeRequest({}))
        await main.tutor_endpoint(FakeRequest({}))

        self.assertEqual(self.mocks["run"].call_count, 1)
        self.mocks["schedule"].assert_called_once()

    async def test_same_call_analyzed_again_after_cache_expiry_updates_card_once(self):
        await main.tutor_endpoint(FakeRequest({}))
        main._TUTOR_CACHE.clear()
        await main.tutor_endpoint(FakeRequest({}))

        self.assertEqual(self.mocks["run"].call_count, 2)
        self.mocks["schedule"].assert_called_once()

    async def test_response_carries_cost_object_and_card_update_does_not(self):
        self.mocks["run"].side_effect = lambda path: ({**TUTORING, "cost_usd": 0.002}, True)
        with mock.patch.object(main, "live_cost_of", return_value=0.01):
            res = await main.tutor_endpoint(FakeRequest({}))

        self.assertEqual(json.loads(res.body)["cost"], {"live": 0.01, "tutoring": 0.002, "total": 0.012})
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

        self.mocks["schedule"].assert_called_once_with({"corrections": TUTORING["corrections"]})

    async def test_teachback_again_after_cache_expiry_updates_card_once(self):
        await self._teachback()
        main._TUTOR_CACHE.clear()
        await self._teachback()

        self.mocks["schedule"].assert_called_once()


class ReadglossWiringTest(unittest.IsolatedAsyncioTestCase):
    setUp = TutorEndpointWiringTest.setUp

    async def test_fresh_tutoring_pushes_to_readgloss_once(self):
        first = await main.tutor_endpoint(FakeRequest({}))
        main._TUTOR_CACHE.clear()
        await main.tutor_endpoint(FakeRequest({}))

        self.mocks["push"].assert_called_once()
        self.assertEqual(self.mocks["push"].call_args.args[1], "English Tutor 통화 2026-10-20")
        self.assertIn(b'"readgloss":{"saved":2}', first.body)

    async def test_bridge_down_gives_null_and_retries_next_time(self):
        self.mocks["push"].return_value = None
        first = await main.tutor_endpoint(FakeRequest({}))
        main._TUTOR_CACHE.clear()
        await main.tutor_endpoint(FakeRequest({}))

        self.assertIn(b'"readgloss":null', first.body)
        self.assertEqual(self.mocks["push"].call_count, 2)

    async def test_card_update_gets_no_readgloss_fields(self):
        await main.tutor_endpoint(FakeRequest({}))

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
}

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
        patcher = mock.patch.object(main, "practice_words", return_value=[])
        self.practice = patcher.start()
        self.addCleanup(patcher.stop)
        pron_patcher = mock.patch.object(pron, "latest_result", return_value=None)
        self.pron_latest = pron_patcher.start()
        self.addCleanup(pron_patcher.stop)

    async def test_slow_bridge_does_not_hold_the_home_screen(self):
        import threading

        release = threading.Event()
        self.addCleanup(release.set)
        self.practice.side_effect = lambda: release.wait(5) and []
        with mock.patch.object(main, "PRACTICE_DEADLINE_SEC", 0.1), \
                mock.patch.object(main, "load_profile", return_value=None):
            body = await main.learner_profile_endpoint()

        self.assertEqual(body["practice_words"], [])

    async def test_readgloss_practice_words_are_passed_through(self):
        self.practice.return_value = [{"lemma": "mitigate", "gloss": "완화하다", "source": "lookup"}]
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


if __name__ == "__main__":
    unittest.main()

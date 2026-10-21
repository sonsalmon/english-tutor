import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from server import clip_translate, main

VIDEO = "vid-tr1"


def fake_model(prefix="KO "):
    """프롬프트 속 Lines JSON을 읽어 줄마다 `KO <영어>`로 답하는 가짜 모델."""

    def generate(prompt):
        lines = json.loads(prompt.split("Lines: ")[1].split("\nContext after:")[0])
        return json.dumps({"items": [{"id": line["id"], "ko": prefix + line["text"]} for line in lines]}, ensure_ascii=False)

    return mock.Mock(side_effect=generate)


class ClipTranslateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "tr.sqlite"
        env = mock.patch.dict(os.environ, {"CLIP_TRANSLATE_CACHE_PATH": str(self.cache), "CLIP_TRANSLATE_DAILY_CAP": "300"})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("CLIP_TRANSLATE_ENABLED", None)
        # 하루 한도는 날짜별로 세므로, 자정을 넘기면 시험이 실패하지 않게 오늘을 고정한다.
        today = mock.patch.object(clip_translate, "_today", return_value="2026-10-22")
        today.start()
        self.addCleanup(today.stop)
        self.client = TestClient(main.app)

    def post(self, model, lines=None, **extra):
        body = {"video_id": VIDEO, "lines": lines or [{"id": 1000, "text": "Hello there."}], **extra}
        with mock.patch("server.tutor.make_generate_text", return_value=model):
            return self.client.post("/api/clips/translate", json=body)

    def test_router_is_mounted_on_the_app(self):
        self.assertIn("/api/clips/translate", {route.path for route in main.app.routes})

    def test_translates_and_returns_the_korean_line(self):
        model = fake_model()
        res = self.post(model, before=["Before."], after=["After one.", "After two.", "After three."])

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["items"], [{"id": 1000, "ko": "KO Hello there.", "cached": False}])
        prompt = model.call_args.args[0]
        self.assertIn('"Before."', prompt)
        self.assertIn('"After one."', prompt)
        self.assertIn('"After two."', prompt)
        self.assertNotIn("After three.", prompt)

    def test_same_line_again_comes_from_cache_without_calling_the_model(self):
        self.post(fake_model())
        model = fake_model()
        res = self.post(model)

        model.assert_not_called()
        self.assertEqual(res.json()["items"], [{"id": 1000, "ko": "KO Hello there.", "cached": True}])

    def test_changed_text_for_the_same_line_id_is_translated_again(self):
        self.post(fake_model())
        model = fake_model("NEW ")
        res = self.post(model, lines=[{"id": 1000, "text": "Hello again."}])

        model.assert_called_once()
        self.assertEqual(res.json()["items"][0], {"id": 1000, "ko": "NEW Hello again.", "cached": False})

    def test_mixed_request_only_sends_the_uncached_lines_to_the_model(self):
        self.post(fake_model())
        model = fake_model()
        res = self.post(model, lines=[{"id": 1000, "text": "Hello there."}, {"id": 2000, "text": "Second."}])

        sent = json.loads(model.call_args.args[0].split("Lines: ")[1].split("\nContext after:")[0])
        self.assertEqual([line["id"] for line in sent], [2000])
        self.assertEqual({i["id"]: i["cached"] for i in res.json()["items"]}, {1000: True, 2000: False})

    def test_cache_lives_outside_the_caption_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            captions = Path(tmp) / "captions.db"
            with mock.patch.dict(os.environ, {"CLIPDB_PATH": str(captions)}):
                os.environ.pop("CLIP_TRANSLATE_CACHE_PATH")
                self.assertEqual(clip_translate.cache_path(), Path(tmp) / "clip-translate-cache.sqlite")
        self.post(fake_model())
        tables = {r[0] for r in sqlite3.connect(self.cache).execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"translations", "usage"} <= tables)

    def test_daily_cap_is_counted_per_day_and_resets_on_the_next_day(self):
        os.environ["CLIP_TRANSLATE_DAILY_CAP"] = "1"
        self.post(fake_model())
        self.assertEqual(self.post(fake_model(), lines=[{"id": 2000, "text": "Other."}]).status_code, 429)

        with mock.patch.object(clip_translate, "_today", return_value="2026-10-23"):
            res = self.post(fake_model(), lines=[{"id": 2000, "text": "Other."}])
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["items"][0]["cached"], False)

    def test_daily_cap_stops_the_model_and_cached_lines_still_work(self):
        os.environ["CLIP_TRANSLATE_DAILY_CAP"] = "2"
        lines = [{"id": i * 1000, "text": f"Line {i}."} for i in range(1, 4)]
        first = self.post(fake_model(), lines=lines)

        self.assertEqual(first.status_code, 200)
        self.assertEqual([i["id"] for i in first.json()["items"]], [1000, 2000])
        self.assertTrue(first.json()["capped"])
        self.assertEqual(first.json()["remaining"], 0)

        model = fake_model()
        refused = self.post(model, lines=[{"id": 9000, "text": "Brand new."}])
        self.assertEqual(refused.status_code, 429)
        model.assert_not_called()

        again = self.post(model, lines=[{"id": 1000, "text": "Line 1."}, {"id": 9000, "text": "Brand new."}])
        self.assertEqual(again.status_code, 200)
        self.assertEqual([(i["id"], i["cached"]) for i in again.json()["items"]], [(1000, True)])
        self.assertTrue(again.json()["capped"])
        model.assert_not_called()

    def test_cached_lines_do_not_use_up_the_cap(self):
        os.environ["CLIP_TRANSLATE_DAILY_CAP"] = "1"
        self.post(fake_model())
        res = self.post(fake_model())

        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.json()["capped"])

    def test_model_failure_gives_no_items_and_uses_no_cap_and_is_not_cached(self):
        os.environ["CLIP_TRANSLATE_DAILY_CAP"] = "1"
        broken = mock.Mock(side_effect=RuntimeError("model down"))
        res = self.post(broken)
        self.assertEqual((res.status_code, res.json()["items"], res.json()["remaining"]), (200, [], 1))

        good = fake_model()
        res = self.post(good)
        good.assert_called_once()
        self.assertEqual(res.json()["items"][0]["cached"], False)

    def test_model_answer_with_unknown_or_empty_items_is_ignored(self):
        junk = mock.Mock(return_value=json.dumps({"items": [{"id": 77, "ko": "엉뚱"}, {"id": 1000, "ko": "  "}, "x"]}))
        res = self.post(junk)
        self.assertEqual(res.json()["items"], [])
        self.assertEqual(self.post(mock.Mock(return_value="not json")).json()["items"], [])

    def test_switched_off_server_is_404_and_never_calls_the_model(self):
        os.environ["CLIP_TRANSLATE_ENABLED"] = "0"
        model = fake_model()
        res = self.post(model)

        self.assertEqual(res.status_code, 404)
        model.assert_not_called()

    def test_bad_requests_are_rejected_before_the_model(self):
        model = fake_model()
        ok = {"id": 1, "text": "Hi."}
        cases = [
            {"video_id": "a b", "lines": [ok]},
            {"video_id": VIDEO, "lines": []},
            {"video_id": VIDEO, "lines": [ok] * 2},
            {"video_id": VIDEO, "lines": [{"id": i, "text": "x"} for i in range(9)]},
            {"video_id": VIDEO, "lines": [{"id": "1", "text": "Hi."}]},
            {"video_id": VIDEO, "lines": [{"id": 1, "text": "   "}]},
            {"lines": [ok]},
            [1, 2],
        ]
        with mock.patch("server.tutor.make_generate_text", return_value=model):
            for body in cases:
                self.assertEqual(self.client.post("/api/clips/translate", json=body).status_code, 400, body)
            self.assertEqual(self.client.post("/api/clips/translate", content="x", headers={"content-type": "text/plain"}).status_code, 415)
        model.assert_not_called()


if __name__ == "__main__":
    unittest.main()

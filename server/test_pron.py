import io
import json
import os
import sys
import tempfile
import unittest
import wave
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import pron

ITEMS = {i["id"]: i for i in pron.load_test()["items"]}


def judge(item_id, heard):
    return pron.judge_item(ITEMS[item_id], heard)


def wav_bytes(seconds=0.1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * int(16000 * seconds))
    return buf.getvalue()


class JudgeTest(unittest.TestCase):
    def test_cant_forms_all_count_as_cant(self):
        for heard in ("I can't go to the meeting tomorrow.", "I can’t go", "I cant go", "I cannot go", "I can not go", "I CAN'T go"):
            with self.subTest(heard=heard):
                self.assertEqual(judge("c2", heard), "target")
                self.assertEqual(judge("c1", heard), "other")

    def test_can_is_heard_only_when_no_cant_form_appears(self):
        self.assertEqual(judge("c1", "I can go to the meeting tomorrow."), "target")
        self.assertEqual(judge("c2", "I can go to the meeting tomorrow."), "other")
        self.assertEqual(judge("c1", "Yes I can, but I can't tomorrow"), "other")

    def test_neither_or_both_words_is_unclear(self):
        self.assertEqual(judge("c1", "I go to the meeting tomorrow."), "unclear")
        self.assertEqual(judge("c1", ""), "unclear")
        self.assertEqual(judge("l1", "Can you collect or correct the data?"), "unclear")
        self.assertEqual(judge("l1", "Can you connect the data?"), "unclear")

    def test_bracket_with_the_pair_is_unclear(self):
        self.assertEqual(judge("c1", "I [can/can't?] go to the meeting"), "unclear")
        self.assertEqual(judge("c2", "I [can’t/can?] go to the meeting"), "unclear")
        self.assertEqual(judge("e1", "We [walk/walked?] to work"), "unclear")
        self.assertEqual(judge("l1", "Can you [collect/correct?] the data?"), "unclear")

    def test_bracket_without_the_pair_does_not_hide_a_clear_word(self):
        self.assertEqual(judge("e1", "We walked to [work/word?]"), "target")

    def test_other_pairs_are_whole_word_and_case_insensitive(self):
        self.assertEqual(judge("p1", "I bought a new PAN."), "target")
        self.assertEqual(judge("p1", "I bought a new fan."), "other")
        self.assertEqual(judge("e1", "We walked to work"), "target")
        self.assertEqual(judge("e1", "We walk to work"), "other")
        self.assertEqual(judge("e2", "We walked to work"), "other")
        self.assertEqual(judge("i1", "Look at that ships."), "unclear")
        self.assertEqual(judge("t1", "I have free tickets."), "other")


class AggregateTest(unittest.TestCase):
    def test_every_contrast_has_a_korean_tip_and_counts(self):
        answers = [
            {"id": "c1", "text": "I can go to the meeting tomorrow."},
            {"id": "c2", "text": "I can go to the meeting tomorrow."},
            {"id": "c4", "text": "She [can/can't?] drive on the highway."},
            {"id": "l1", "text": "Can you correct the data?"},
            {"id": "l2", "text": "Can you correct the data?"},
        ]

        rows = {r["contrast"]: r for r in pron.judge_answers(answers)}

        self.assertEqual(set(rows), set(pron.load_test()["contrasts"]))
        self.assertEqual(len(rows), 7)
        for key, row in rows.items():
            with self.subTest(contrast=key):
                self.assertGreater(len(row["tip"]), 20)
                self.assertTrue(any("가" <= ch <= "힣" for ch in row["tip"]))
        can = rows["can_cant"]
        self.assertEqual(
            {k: can[k] for k in ("label", "total", "as_target", "as_other", "unclear")},
            {"label": "can / can't", "total": 3, "as_target": 1, "as_other": 1, "unclear": 1},
        )
        self.assertEqual(can["misheard"], [{"target": "can't", "heard_text": "I can go to the meeting tomorrow."}])
        l_r = rows["l_r"]
        self.assertEqual((l_r["total"], l_r["as_target"], l_r["as_other"]), (2, 1, 1))
        self.assertEqual(l_r["misheard"][0]["target"], "collect")
        self.assertEqual(rows["ed"]["total"], 0)

    def test_unclear_answer_keeps_its_heard_text_outside_misheard(self):
        item = ITEMS["c1"]
        heard = "Hello there, nice weather."

        rows = {r["contrast"]: r for r in pron.judge_answers([{"id": "c1", "text": heard}])}

        row = rows[item["contrast"]]
        self.assertEqual(row["unclear"], 1)
        self.assertEqual(row["unclear_heard"], [{"target": item["target"], "heard_text": heard}])
        self.assertEqual(row["misheard"], [])

    def test_tips_cover_all_seven_contrasts(self):
        self.assertEqual(set(pron.TIPS), set(pron.load_test()["contrasts"]))


class BuildTestTest(unittest.TestCase):
    def test_items_are_shuffled_and_leak_neither_target_nor_other(self):
        payload = pron.build_test()

        self.assertEqual(len(payload["items"]), 26)
        self.assertEqual({tuple(sorted(i)) for i in payload["items"]}, {("id", "text")})
        self.assertEqual({i["id"] for i in payload["items"]}, set(ITEMS))
        self.assertEqual(payload["contrasts"]["can_cant"], "can / can't")

    def test_order_comes_from_shuffle(self):
        with mock.patch.object(pron.random, "shuffle", side_effect=lambda items: items.reverse()) as shuffle:
            ids = [i["id"] for i in pron.build_test()["items"]]

        shuffle.assert_called_once()
        self.assertEqual(ids, list(reversed(list(ITEMS))))


class BriefTest(unittest.TestCase):
    ANSWERS = [
        {"id": "c1", "text": "I can go to the meeting tomorrow."},
        {"id": "c2", "text": "I can go to the meeting tomorrow."},
        {"id": "c4", "text": "She can drive on the highway."},
        {"id": "c5", "text": "We can finish it by Friday."},
        {"id": "c7", "text": "You can park here."},
        {"id": "l1", "text": "Can you collect the data?"},
        {"id": "l2", "text": "Can you collect the data?"},
        {"id": "p1", "text": "I bought a new pan."},
    ]

    def result(self, answers):
        return {"date": "2026-10-20", "contrasts": pron.judge_answers(answers)}

    def test_brief_names_only_weak_contrasts_and_how_to_ask(self):
        brief = pron.pron_brief(self.result(self.ANSWERS))

        self.assertEqual(
            brief,
            "Pronunciation check (reading test 2026-10-20): "
            "can / can't: can't was heard as can in 4 of 4 sentences; "
            "l / r: correct was heard as collect in 1 of 1 sentences.\n"
            "When you are not sure which of these words the learner said, ask briefly, e.g. 'Did you mean can or can't?'",
        )
        self.assertNotIn("p / f", brief)

    def test_unclear_only_contrast_is_reported(self):
        brief = pron.pron_brief(self.result([{"id": "p1", "text": "I bought a new [pan/fan?]."}]))

        self.assertIn("p / f: could not tell in 1 of 1 sentences", brief)

    def test_no_weak_contrast_or_no_result_gives_empty_brief(self):
        self.assertEqual(pron.pron_brief(self.result([{"id": "p1", "text": "I bought a new pan."}])), "")
        self.assertEqual(pron.pron_brief(None), "")

    def test_weak_summary_lists_label_counts(self):
        summary = pron.weak_summary(self.result(self.ANSWERS))

        self.assertEqual(summary["date"], "2026-10-20")
        self.assertEqual(
            summary["weak"][0],
            {
                "label": "can / can't",
                "as_other": 4,
                "unclear": 0,
                "total": 5,
                "worst": {"target": "can't", "other": "can", "as_other": 4, "unclear": 0, "total": 4},
            },
        )
        self.assertIsNone(pron.weak_summary(None))

    def test_direction_totals_count_per_target(self):
        answers = [
            {"id": "c2", "text": "I can go to the meeting tomorrow."},
            {"id": "c4", "text": "She can drive on the highway."},
            {"id": "c5", "text": "We can't finish it by Friday."},
            {"id": "c7", "text": "You can't park here."},
        ]

        rows = {r["contrast"]: r for r in pron.judge_answers(answers)}

        cant = next(d for d in rows["can_cant"]["directions"] if d["target"] == "can't")
        self.assertEqual(cant, {"target": "can't", "other": "can", "total": 4, "as_target": 2, "as_other": 2, "unclear": 0})
        self.assertEqual([d["target"] for d in rows["can_cant"]["directions"]], ["can", "can't"])

    def test_brief_uses_direction_totals_and_stays_under_600_chars(self):
        answers = [
            {"id": "c2", "text": "I can go to the meeting tomorrow."},
            {"id": "c4", "text": "She can drive on the highway."},
            {"id": "c5", "text": "We can't finish it by Friday."},
            {"id": "c7", "text": "You can't park here."},
        ]
        self.assertIn("in 2 of 4 sentences", pron.pron_brief(self.result(answers)))

        everything_wrong = [{"id": i["id"], "text": f"I said {i['other']} today."} for i in ITEMS.values()]
        brief = pron.pron_brief(self.result(everything_wrong))
        self.assertLessEqual(len(brief), 600)
        self.assertTrue(brief.startswith("Pronunciation check (reading test 2026-10-20): "))
        self.assertTrue(brief.endswith("'Did you mean can or can't?'"))

    def test_brief_drops_whole_contrast_parts_when_over_the_cap(self):
        everything_wrong = [{"id": i["id"], "text": f"I said {i['other']} today."} for i in ITEMS.values()]
        result = self.result(everything_wrong)
        with mock.patch.object(pron, "BRIEF_MAX_CHARS", 300):
            brief = pron.pron_brief(result)

        self.assertIn("can / can't", brief)
        self.assertNotIn("b / v", brief)
        self.assertTrue(brief.endswith("'Did you mean can or can't?'"))


class PronHttpTest(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from server import main

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.pron_dir = Path(tmp.name) / "pron"
        patcher = mock.patch.dict(os.environ, {pron.PRON_DIR_ENV: str(self.pron_dir)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client = TestClient(main.app)

    def transcribe(self, body, content_type="audio/wav"):
        return self.client.post("/api/pron/transcribe", content=body, headers={"content-type": content_type})

    def test_test_endpoint_hides_the_answers(self):
        res = self.client.get("/api/pron/test")

        self.assertEqual(res.status_code, 200)
        items = res.json()["items"]
        self.assertEqual(len(items), 26)
        self.assertEqual({tuple(sorted(i)) for i in items}, {("id", "text")})
        self.assertNotIn("target", res.text)
        self.assertNotIn("other", res.text)

    def test_transcribe_sends_only_the_audio_to_the_transcriber(self):
        data = wav_bytes()
        with mock.patch.object(pron, "transcribe_wav", return_value="I can go.") as fake:
            res = self.transcribe(data)

        self.assertEqual((res.status_code, res.json()), (200, {"text": "I can go."}))
        fake.assert_called_once_with(data)

    def test_transcribe_content_type_size_and_format_checks(self):
        with mock.patch.object(pron, "transcribe_wav", return_value="x") as fake:
            self.assertEqual(self.transcribe(wav_bytes(), "application/json").status_code, 415)
            self.assertEqual(self.transcribe(wav_bytes(), "text/plain").status_code, 415)
            self.assertEqual(self.transcribe(b"RIFF" + b"\x00" * (pron.MAX_WAV_BYTES + 1)).status_code, 413)
            self.assertEqual(self.transcribe(b"").status_code, 400)
            self.assertEqual(self.transcribe(b"not a wav file at all, just text" * 4).status_code, 400)
            self.assertEqual(self.transcribe(wav_bytes(), "audio/wav; charset=binary").status_code, 200)

        fake.assert_called_once()

    def test_transcribe_model_failure_is_502_with_korean_detail(self):
        with mock.patch.object(pron, "transcribe_wav", side_effect=RuntimeError("vertex down")):
            res = self.transcribe(wav_bytes())

        self.assertEqual(res.status_code, 502)
        self.assertEqual(res.json(), {"detail": "발음을 받아쓰지 못했어요. 잠시 후 다시 해 주세요."})

    def test_finish_saves_a_timestamped_file_and_latest_returns_it(self):
        self.assertEqual(self.client.get("/api/pron/latest").json(), {"result": None})
        answers = [
            {"id": "c1", "text": "I can go to the meeting tomorrow."},
            {"id": "c2", "text": "I can go to the meeting tomorrow."},
            {"id": "l1", "text": "Can you collect the data?"},
        ]

        res = self.client.post("/api/pron/finish", json={"answers": answers})

        self.assertEqual(res.status_code, 200)
        result = res.json()
        rows = {r["contrast"]: r for r in result["contrasts"]}
        self.assertEqual(
            {k: rows["can_cant"][k] for k in ("total", "as_target", "as_other", "unclear")},
            {"total": 2, "as_target": 1, "as_other": 1, "unclear": 0},
        )
        self.assertEqual((rows["l_r"]["total"], rows["l_r"]["as_target"]), (1, 1))
        self.assertEqual(len(result["contrasts"]), 7)
        [saved] = list(self.pron_dir.glob("*.json"))
        self.assertRegex(saved.name, r"^\d{4}-\d{2}-\d{2}-\d{6}\.json$")
        self.assertEqual(json.loads(saved.read_text(encoding="utf-8")), result)
        self.assertEqual(self.client.get("/api/pron/latest").json(), result)

    def test_latest_picks_the_newest_file(self):
        for stamp in (datetime(2026, 10, 19, 9, 0, 0), datetime(2026, 10, 20, 9, 0, 0)):
            pron.finish([{"id": "p1", "text": "I bought a new pan."}], now=stamp)

        self.assertEqual(pron.latest_result()["date"], "2026-10-20")

    def test_finish_rejects_bad_bodies(self):
        for body in ({}, {"answers": []}, {"answers": "x"}, {"answers": [{"id": "zz", "text": "x"}]}, {"answers": [{"id": "c1"}]},
                     {"answers": [{"id": "c1", "text": "x" * 501}]}, {"answers": [{"id": "c1", "text": "x"}] * 41}):
            with self.subTest(body=str(body)[:40]):
                self.assertEqual(self.client.post("/api/pron/finish", json=body).status_code, 400)
        res = self.client.post("/api/pron/finish", content="{}", headers={"content-type": "text/plain"})
        self.assertEqual(res.status_code, 415)
        self.assertFalse(self.pron_dir.exists())


class SessionCostTest(unittest.TestCase):
    def test_transcription_cost_is_taken_once_by_finish(self):
        from types import SimpleNamespace

        from google.genai import types

        usage = SimpleNamespace(
            prompt_token_count=1000,
            candidates_token_count=20,
            thoughts_token_count=0,
            tool_use_prompt_token_count=0,
            prompt_tokens_details=[SimpleNamespace(modality=types.MediaModality.AUDIO, token_count=900)],
            candidates_tokens_details=None,
        )
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {pron.PRON_DIR_ENV: tmp}):
            pron.add_session_usage(SimpleNamespace(usage_metadata=usage))
            first = pron.finish([{"id": "p1", "text": "pan"}], model="gemini-2.5-flash")
            second = pron.finish([{"id": "p1", "text": "pan"}], now=datetime(2026, 10, 20, 9, 0, 1), model="gemini-2.5-flash")

        self.assertEqual(first["cost_usd"], round((100 * 0.30 + 900 * 1.00 + 20 * 2.50) / 1_000_000, 6))
        self.assertIsNone(second["cost_usd"])


if __name__ == "__main__":
    unittest.main()

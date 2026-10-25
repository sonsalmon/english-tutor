import json
import os
import sys
import tempfile
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import drill, learner_profile

DAY1 = datetime(2026, 10, 25, 10, 0, tzinfo=drill.KST)
DAY2 = datetime(2026, 10, 26, 10, 0, tzinfo=drill.KST)


def good_payload():
    return {
        "questions": [
            {"type": "blank", "focus": "past tense", "prompt": "Yesterday I ____ to the office.", "answer": "went", "accept": [], "explanation_ko": "어제 일이라 과거형 went를 써요."},
            {"type": "blank", "focus": "articles", "prompt": "She is ____ engineer.", "answer": "an", "explanation_ko": "모음 소리 앞에는 an을 써요."},
            {"type": "choice", "focus": "prepositions", "prompt": "I'm good ____ math.", "options": ["at", "in", "on"], "answer": "at", "explanation_ko": "good at이 짝이에요."},
            {"type": "choice", "focus": "plurals", "prompt": "I have two ____.", "options": ["child", "children", "childs"], "answer": "children", "explanation_ko": "child의 복수는 children이에요."},
            {"type": "rephrase", "focus": "past tense", "prompt": "I go to the store yesterday.", "answer": "I went to the store yesterday.", "accept": ["Yesterday I went to the store."], "explanation_ko": "yesterday가 있으니 went로 바꿔요."},
        ]
    }


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        card = learner_profile.empty_profile()
        card["weak_points"] = [{"pattern": "past tense", "count": 3, "last_seen": "2026-10-24", "example": "I go yesterday"}]
        profile = root / "learner-profile.json"
        profile.write_text(json.dumps(card), encoding="utf-8")
        patcher = mock.patch.dict(os.environ, {"LEARNER_PROFILE_PATH": str(profile), "DRILL_DIR": str(root / "drills")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.profile = profile
        self.calls = 0

    def fake(self, payload=None):
        def generate(prompt):
            self.calls += 1
            self.last_prompt = prompt
            return json.dumps(payload or good_payload())

        return generate


class GetDrillTest(Env):
    def test_generates_once_per_day_and_reuses_cache(self):
        first = drill.get_drill(DAY1, self.fake())
        second = drill.get_drill(DAY1, self.fake())
        self.assertEqual(self.calls, 1)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["questions"], second["questions"])
        self.assertIn("past tense", self.last_prompt)
        self.assertIn("I go yesterday", self.last_prompt)

    def test_new_day_generates_again(self):
        drill.get_drill(DAY1, self.fake())
        drill.get_drill(DAY2, self.fake())
        self.assertEqual(self.calls, 2)

    def test_no_weak_points_never_calls_model(self):
        card = learner_profile.empty_profile()
        self.profile.write_text(json.dumps(card), encoding="utf-8")
        with self.assertRaises(drill.NoWeakPoints):
            drill.get_drill(DAY1, self.fake())
        self.assertEqual(self.calls, 0)

    def test_missing_card_is_no_weak_points(self):
        self.profile.unlink()
        with self.assertRaises(drill.NoWeakPoints):
            drill.get_drill(DAY1, self.fake())

    def test_invalid_output_retries_once_then_succeeds(self):
        outputs = iter(["not json", json.dumps(good_payload())])

        def generate(prompt):
            self.calls += 1
            return next(outputs)

        drill.get_drill(DAY1, generate)
        self.assertEqual(self.calls, 2)

    def test_two_invalid_outputs_fail_and_cache_nothing(self):
        bad = {"questions": good_payload()["questions"][:3]}
        with self.assertRaises(drill.DrillError):
            drill.get_drill(DAY1, self.fake(bad))
        self.assertEqual(self.calls, 2)
        self.assertEqual(list(drill.get_drill_dir().glob("drill-*.json")), [])

    def test_corrupt_cache_is_regenerated(self):
        drill.get_drill(DAY1, self.fake())
        (drill.get_drill_dir() / "drill-2026-10-25.json").write_text("{broken", encoding="utf-8")
        drill.get_drill(DAY1, self.fake())
        self.assertEqual(self.calls, 2)

    def test_concurrent_opens_generate_once(self):
        gate = threading.Event()

        def generate(prompt):
            self.calls += 1
            gate.wait(0.2)
            return json.dumps(good_payload())

        threads = [threading.Thread(target=drill.get_drill, args=(DAY1, generate)) for _ in range(4)]
        for t in threads:
            t.start()
        gate.set()
        for t in threads:
            t.join(5)
        self.assertEqual(self.calls, 1)


class ValidateTest(unittest.TestCase):
    def reject(self, mutate):
        payload = good_payload()
        mutate(payload["questions"])
        with self.assertRaises(ValueError):
            drill.validate_questions(payload)

    def test_good_payload_gets_ids_and_normalizes_blank(self):
        payload = good_payload()
        payload["questions"][0]["prompt"] = "Yesterday I ______ to the office."
        qs = drill.validate_questions(payload)
        self.assertEqual([q["id"] for q in qs], ["q1", "q2", "q3", "q4", "q5"])
        self.assertEqual(qs[0]["prompt"], "Yesterday I ____ to the office.")

    def test_rejections(self):
        self.reject(lambda qs: qs[0].update(type="essay"))
        self.reject(lambda qs: qs[0].update(prompt="No blank here."))
        self.reject(lambda qs: qs[0].update(prompt="Two ____ blanks ____."))
        self.reject(lambda qs: qs[2].update(answer="by"))
        self.reject(lambda qs: qs[2].update(options=["at", "at", "on"]))
        self.reject(lambda qs: qs[2].update(options=["at", "on"]))
        self.reject(lambda qs: qs[1].pop("explanation_ko"))
        self.reject(lambda qs: qs.pop())

    def test_non_object_is_rejected(self):
        for raw in (None, [], {"questions": "x"}):
            with self.assertRaises(ValueError):
                drill.validate_questions(raw)


class PublicAndCheckTest(Env):
    def setUp(self):
        super().setUp()
        self.drill = drill.get_drill(DAY1, self.fake())

    def test_public_hides_answers(self):
        shown = json.dumps(drill.public(self.drill), ensure_ascii=False)
        for secret in ("went", "explanation", "accept", "answer"):
            self.assertNotIn(secret, shown)
        self.assertIn("options", shown)

    def check(self, qid, answer):
        return drill.check_answer("2026-10-25", qid, answer)

    def test_blank_ignores_case_punctuation_and_accepts_full_sentence(self):
        for given in ("went", " Went. ", "Yesterday I went to the office."):
            with self.subTest(given=given):
                self.assertTrue(self.check("q1", given)["correct"])
        self.assertFalse(self.check("q1", "go")["correct"])
        self.assertFalse(self.check("q1", "")["correct"])

    def test_choice(self):
        self.assertTrue(self.check("q4", "children")["correct"])
        wrong = self.check("q4", "childs")
        self.assertFalse(wrong["correct"])
        self.assertEqual(wrong["answer"], "children")
        self.assertIn("children", wrong["explanation"])
        self.assertFalse(wrong["loose"])

    def test_rephrase_accepts_alternates_and_marks_wrong_as_loose(self):
        self.assertTrue(self.check("q5", "yesterday I went to the store")["correct"])
        miss = self.check("q5", "I visited the store yesterday.")
        self.assertFalse(miss["correct"])
        self.assertTrue(miss["loose"])

    def test_bad_requests(self):
        with self.assertRaises(LookupError):
            self.check("q9", "x")
        with self.assertRaises(LookupError):
            drill.check_answer("2026-01-01", "q1", "x")
        with self.assertRaises(ValueError):
            self.check("q1", 5)
        with self.assertRaises(ValueError):
            drill.check_answer("../../etc", "q1", "x")


if __name__ == "__main__":
    unittest.main()

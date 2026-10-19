import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import learner_profile as lp

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=lp.KST)
LEVEL = {"cefr": "B1.2", "actfl": "Intermediate High", "source": "level-test 2026-10-07"}


def weak(pattern, count=1, last_seen="2026-10-16", misses=0):
    return {"pattern": pattern, "count": count, "last_seen": last_seen, "example": "I just started my day.", "misses": misses}


def card(**overrides):
    base = {
        "updated": "2026-10-16T21:40:00+09:00",
        "level": dict(LEVEL),
        "weak_points": [weak("past tense")],
        "fixed_points": [],
        "phrases": [{"phrase": "based out of", "first_seen": "2026-10-16", "used_well": 0}],
        "pragmatics": [{"pattern": "returning the question", "note": "How about you? keeps the talk going."}],
        "interests": ["security"],
        "next_goal": "Use past tense in questions.",
    }
    base.update(overrides)
    return base


class ProfileFileTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "learner-profile.json"
        self.history = Path(self._tmp.name) / lp.HISTORY_DIR_NAME

    def tearDown(self):
        self._tmp.cleanup()

    def write_card(self, data):
        self.path.write_text(json.dumps(data), encoding="utf-8")
        return self.path.read_bytes()

    def update(self, model_output):
        return lp.update_profile({"corrections": []}, generate_text=lambda prompt: model_output, path=self.path, now=NOW)

    def test_valid_update_writes_card_and_backup(self):
        self.write_card(card())
        new = card(weak_points=[weak("past tense", count=2, last_seen="2026-10-20")], next_goal="Ask with did.")

        self.assertTrue(self.update(json.dumps(new)))

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["next_goal"], "Ask with did.")
        self.assertEqual(saved["updated"], "2026-10-20T09:00:00+09:00")
        backups = list(self.history.glob("*.json"))
        self.assertEqual([b.name for b in backups], ["20261020-090000.json"])
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8"))["next_goal"], "Use past tense in questions.")

    def test_missing_card_is_created_without_backup(self):
        self.assertTrue(self.update(json.dumps(card())))

        self.assertTrue(self.path.exists())
        self.assertFalse(self.history.exists())

    def test_non_json_output_keeps_card(self):
        before = self.write_card(card())

        self.assertFalse(self.update("Sure! Here is the card."))

        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.history.exists())

    def test_schema_invalid_output_keeps_card(self):
        before = self.write_card(card())
        broken = card()
        del broken["phrases"]

        self.assertFalse(self.update(json.dumps(broken)))

        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(self.history.exists())

    def test_model_cannot_change_level(self):
        self.write_card(card())

        self.assertTrue(self.update(json.dumps(card(level={"cefr": "C2", "actfl": "Superior", "source": "model"}))))

        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["level"], LEVEL)

    def test_weak_points_capped_at_five_by_count(self):
        self.write_card(card())
        many = [weak(f"pattern {i}", count=i + 1) for i in range(7)]

        self.assertTrue(self.update(json.dumps(card(weak_points=many))))

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([p["count"] for p in saved["weak_points"]], [7, 6, 5, 4, 3])

    def test_three_misses_moves_to_fixed_points(self):
        self.write_card(card())
        points = [weak("past tense", misses=3), weak("articles", misses=1)]

        self.assertTrue(self.update(json.dumps(card(weak_points=points))))

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([p["pattern"] for p in saved["weak_points"]], ["articles"])
        self.assertEqual([p["pattern"] for p in saved["fixed_points"]], ["past tense"])
        self.assertNotIn("misses", saved["fixed_points"][0])


class BriefTest(unittest.TestCase):
    def test_empty_card_gives_empty_brief(self):
        self.assertEqual(lp.profile_brief(None), "")

    def test_brief_mentions_level_weak_point_and_goal(self):
        brief = lp.profile_brief(lp.validate_profile(card()))

        self.assertIn("B1.2", brief)
        self.assertIn("past tense", brief)
        self.assertIn("Use past tense in questions", brief)

    def test_brief_stays_within_limit_for_large_card(self):
        big = card(
            weak_points=[weak("x" * 300, count=5) for _ in range(5)],
            phrases=[{"phrase": "p" * 100, "first_seen": "2026-10-16", "used_well": 0} for _ in range(15)],
            pragmatics=[{"pattern": "q" * 200, "note": "n" * 200} for _ in range(8)],
            next_goal="g" * 500,
        )

        self.assertLessEqual(len(lp.profile_brief(lp.validate_profile(big))), lp.BRIEF_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()

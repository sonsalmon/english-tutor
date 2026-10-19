import copy
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from learner_profile import (
    BRIEF_MAX_CHARS,
    ProfileError,
    build_initial_card,
    empty_profile,
    load_profile,
    profile_brief,
    update_profile,
)

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 20, 9, 30, 15, tzinfo=KST)
TUTORING = {"corrections": [{"said": "I start", "better": "I started", "why": "과거형"}]}


def weak(pattern, count=1, last_seen="2026-10-16", misses=0):
    return {"pattern": pattern, "count": count, "last_seen": last_seen, "example": "ex " + pattern, "misses": misses}


def card(**over):
    base = {
        "updated": "2026-10-16T09:00:00+09:00",
        "level": {"cefr": "B1.2", "actfl": "Intermediate High", "source": "level-test 2026-10-07"},
        "weak_points": [weak("past tense", 2)],
        "fixed_points": [],
        "phrases": [{"phrase": "based out of", "first_seen": "2026-10-16", "used_well": 0}],
        "pragmatics": [{"pattern": "bottom line first", "note": "Lead with the result."}],
        "interests": ["hiking"],
        "next_goal": "question tense",
    }
    base.update(over)
    return base


class ProfileTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.path = self.dir / "learner-profile.json"
        self.history = self.dir / "learner-profile-history"

    def seed(self, data=None):
        self.path.write_text(json.dumps(data or card(), ensure_ascii=False), encoding="utf-8")

    def update(self, output):
        return update_profile(TUTORING, generate_text=lambda _prompt: output, path=self.path, now=NOW)

    def history_files(self):
        return sorted(self.history.glob("*.json")) if self.history.exists() else []


class UpdateTest(ProfileTestCase):
    def test_valid_update_writes_card_and_backup(self):
        old_bytes = json.dumps(card(), ensure_ascii=False).encode("utf-8")
        self.path.write_bytes(old_bytes)
        new = card(weak_points=[weak("past tense", 3, "2026-10-20")], next_goal="new goal")
        self.assertTrue(self.update(json.dumps(new)))
        saved = load_profile(self.path)
        self.assertEqual(saved["next_goal"], "new goal")
        self.assertEqual(saved["weak_points"][0]["count"], 3)
        self.assertEqual(saved["updated"], "2026-10-20T09:30:15+09:00")
        self.assertNotEqual(saved["updated"], card()["updated"])
        backups = self.history_files()
        self.assertEqual([b.name for b in backups], ["20261020-093015.json"])
        self.assertEqual(backups[0].read_bytes(), old_bytes)
        self.assertEqual(list(self.dir.glob("*.tmp")), [])

    def test_missing_card_starts_from_empty_default(self):
        prompts = []

        def gen(prompt):
            prompts.append(prompt)
            return json.dumps(card())

        self.assertTrue(update_profile(TUTORING, generate_text=gen, path=self.path, now=NOW))
        self.assertIn('"weak_points": []', prompts[0])
        self.assertEqual(self.history_files(), [])
        self.assertEqual(load_profile(self.path)["level"], empty_profile()["level"])

    def test_code_fenced_json_is_accepted(self):
        self.seed()
        self.assertTrue(self.update("```json\n" + json.dumps(card(next_goal="g")) + "\n```"))
        self.assertEqual(load_profile(self.path)["next_goal"], "g")

    def test_non_json_leaves_card_untouched(self):
        self.seed()
        before = self.path.read_bytes()
        self.assertFalse(self.update("sorry, I cannot do that"))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.history_files(), [])

    def test_generate_text_exception_leaves_card_untouched(self):
        self.seed()
        before = self.path.read_bytes()

        def boom(_prompt):
            raise RuntimeError("vertex down")

        self.assertFalse(update_profile(TUTORING, generate_text=boom, path=self.path, now=NOW))
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.history_files(), [])

    def test_schema_invalid_leaves_card_untouched(self):
        self.seed()
        before = self.path.read_bytes()
        bad_variants = []
        missing_key = card()
        del missing_key["interests"]
        bad_variants.append(missing_key)
        bad_variants.append(card(weak_points=[{"pattern": "x", "count": "2", "last_seen": "2026-10-16", "example": "e"}]))
        bad_variants.append(card(weak_points=[weak("x", last_seen="16/10/2026")]))
        bad_variants.append(card(phrases=[{"phrase": "p", "first_seen": "2026-10-16"}]))
        bad_variants.append(card(interests=[1]))
        bad_variants.append({**card(), "extra": 1})
        for bad in bad_variants:
            self.assertFalse(self.update(json.dumps(bad)), bad)
            self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.history_files(), [])

    def test_corrupt_existing_card_is_not_overwritten(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertFalse(self.update(json.dumps(card())))
        self.assertEqual(self.path.read_text(encoding="utf-8"), "{not json")

    def test_level_is_restored_from_old_card(self):
        self.seed()
        changed = card(level={"cefr": "C2", "actfl": "Superior", "source": "call"})
        self.assertTrue(self.update(json.dumps(changed)))
        self.assertEqual(load_profile(self.path)["level"], card()["level"])

    def test_weak_points_capped_at_five_by_count_then_recency(self):
        self.seed()
        points = [weak(f"p{i}", count=i, last_seen="2026-10-1%d" % (i % 10)) for i in range(1, 8)]
        points.append(weak("tie-old", count=7, last_seen="2026-09-01"))
        self.assertTrue(self.update(json.dumps(card(weak_points=points))))
        patterns = [p["pattern"] for p in load_profile(self.path)["weak_points"]]
        self.assertEqual(len(patterns), 5)
        self.assertEqual(patterns, ["p7", "tie-old", "p6", "p5", "p4"])

    def test_misses_three_moves_to_fixed_points(self):
        self.seed()
        points = [weak("stale", 4, misses=3), weak("fresh", 2, misses=2)]
        self.assertTrue(self.update(json.dumps(card(weak_points=points))))
        saved = load_profile(self.path)
        self.assertEqual([p["pattern"] for p in saved["weak_points"]], ["fresh"])
        self.assertEqual([p["pattern"] for p in saved["fixed_points"]], ["stale"])
        self.assertNotIn("misses", saved["fixed_points"][0])

    def test_misses_defaults_to_zero_when_model_omits_it(self):
        self.seed()
        point = weak("p")
        del point["misses"]
        self.assertTrue(self.update(json.dumps(card(weak_points=[point]))))
        self.assertEqual(load_profile(self.path)["weak_points"][0]["misses"], 0)

    def test_prompt_forbids_names_addresses_and_companies(self):
        self.seed()
        prompts = []

        def gen(prompt):
            prompts.append(prompt)
            return json.dumps(card())

        update_profile(TUTORING, generate_text=gen, path=self.path, now=NOW)
        for word in ("names", "addresses", "company"):
            self.assertIn(word, prompts[0])

    def test_same_second_backups_do_not_collide(self):
        self.seed()
        self.assertTrue(self.update(json.dumps(card(next_goal="a"))))
        self.assertTrue(self.update(json.dumps(card(next_goal="b"))))
        self.assertEqual(len(self.history_files()), 2)


class InitialCardTest(ProfileTestCase):
    def test_keeps_model_level_and_enforces_rules(self):
        out = build_initial_card(
            "material",
            generate_text=lambda _p: json.dumps(card(weak_points=[weak(f"p{i}", i) for i in range(8)])),
            now=NOW,
        )
        self.assertEqual(out["level"]["cefr"], "B1.2")
        self.assertEqual(len(out["weak_points"]), 5)
        self.assertEqual(out["updated"], "2026-10-20T09:30:15+09:00")

    def test_invalid_output_raises(self):
        with self.assertRaises(ProfileError):
            build_initial_card("m", generate_text=lambda _p: "nope", now=NOW)


class BriefTest(unittest.TestCase):
    def test_empty_card_gives_empty_string(self):
        self.assertEqual(profile_brief(None), "")
        self.assertEqual(profile_brief({}), "")
        self.assertEqual(profile_brief(empty_profile()), "")

    def test_brief_mentions_key_fields_and_is_deterministic(self):
        brief = profile_brief(card())
        for fragment in ("B1.2", "past tense", "ex past tense", "based out of", "bottom line first", "question tense"):
            self.assertIn(fragment, brief)
        self.assertEqual(brief, profile_brief(copy.deepcopy(card())))

    def test_brief_never_exceeds_limit(self):
        long = "x" * 400
        big = card(
            weak_points=[weak(long + str(i), 5 - i % 3) for i in range(5)],
            phrases=[{"phrase": long, "first_seen": "2026-10-16", "used_well": i} for i in range(20)],
            pragmatics=[{"pattern": long, "note": long} for _ in range(8)],
            interests=[long] * 8,
            next_goal=long,
        )
        brief = profile_brief(big)
        self.assertTrue(0 < len(brief) <= BRIEF_MAX_CHARS)


if __name__ == "__main__":
    unittest.main()

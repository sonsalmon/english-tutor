import json
import os
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

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
        patcher = mock.patch.dict(os.environ, {"MEMORY_SETTINGS_PATH": str(Path(self._tmp.name) / "memory-settings.json")})
        patcher.start()
        self.addCleanup(patcher.stop)

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

        self.assertTrue(self.update("Sure! Here is the card."))  # 모델 실패여도 thinking_gaps 병합 저장

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        old = json.loads(before)
        self.assertEqual({k: v for k, v in saved.items() if k not in ("updated", "thinking_gaps")}, {k: v for k, v in old.items() if k != "updated"})
        self.assertEqual(len(list(self.history.glob("*.json"))), 1)

    def test_schema_invalid_output_keeps_card(self):
        before = self.write_card(card())
        broken = card()
        del broken["phrases"]

        self.assertTrue(self.update(json.dumps(broken)))  # 모델 값은 버리고 기존 카드 유지

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(saved["phrases"]), len(json.loads(before)["phrases"]))
        self.assertEqual(len(list(self.history.glob("*.json"))), 1)

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

    def test_interests_switch_off_keeps_stored_interests(self):
        self.write_card(card(interests=["security"]))
        Path(os.environ["MEMORY_SETTINGS_PATH"]).write_text(
            json.dumps({"version": 1, "about_me": "", "remember": {"facts": True, "threads": True, "interests": False}}), encoding="utf-8"
        )

        self.assertTrue(self.update(json.dumps(card(interests=["security", "jazz"], next_goal="Ask with did."))))

        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["interests"], ["security"])
        self.assertEqual(saved["next_goal"], "Ask with did.")  # 관심사 밖의 갱신은 그대로 반영된다

    def test_interests_switch_on_adds_new_interests(self):
        self.write_card(card(interests=["security"]))

        self.assertTrue(self.update(json.dumps(card(interests=["security", "jazz"]))))

        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["interests"], ["security", "jazz"])


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


def gap(korean, english, kind="framing", count=1, last_seen="2026-10-16", note="노트"):
    return {"korean": korean, "english": english, "kind": kind, "note": note, "count": count, "last_seen": last_seen}


def tgap(korean, english, kind="framing", note="새 노트"):
    return {"korean": korean, "english": english, "kind": kind, "note": note}


class ThinkingGapsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "learner-profile.json"
        patcher = mock.patch.dict(os.environ, {"MEMORY_SETTINGS_PATH": str(Path(self._tmp.name) / "memory-settings.json")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def test_old_card_without_key_validates_to_empty_list(self):
        self.assertEqual(lp.validate_profile(card())["thinking_gaps"], [])
        self.assertEqual(lp.empty_profile(NOW)["thinking_gaps"], [])

    def test_validate_accepts_good_and_rejects_bad_shapes(self):
        ok = lp.validate_profile(card(thinking_gaps=[gap("정신없다", "I'm swamped")]))
        self.assertEqual(ok["thinking_gaps"][0]["english"], "I'm swamped")
        bad = [
            [gap("정신없다", "swamped", kind="grammar")],
            [gap("", "swamped")],
            [{**gap("a", "b"), "count": -1}],
            [{**gap("a", "b"), "last_seen": "yesterday"}],
            [{**gap("a", "b"), "extra": 1}],
            [{k: v for k, v in gap("a", "b").items() if k != "note"}],
            ["swamped"],
            "swamped",
        ]
        for value in bad:
            with self.assertRaises(lp.ProfileError, msg=repr(value)):
                lp.validate_profile(card(thinking_gaps=value))

    def test_merge_counts_dedupes_by_english_or_korean(self):
        old = [gap("정신없다", "I'm swamped", count=2), gap("빈둥빈둥", "lazing around", kind="word", count=1)]
        new = [
            tgap("바쁜", "im swamped!", note="최신 노트"),  # english 정규화가 같다
            tgap("빈둥 빈둥", "loafing", kind="word"),  # korean 정규화가 같다
            tgap("입맛에 안 맞다", "It wasn't to my taste"),
            tgap("입맛에 안 맞다", "not my taste"),  # 같은 통화 안 중복은 한 번만 셌다
            tgap("x", "y", kind="grammar"),  # 잘못된 kind는 건너뛴다
        ]
        merged = lp.merge_thinking_gaps(old, new, "2026-10-20")
        by_en = {g["english"]: g for g in merged}
        self.assertEqual(set(by_en), {"I'm swamped", "lazing around", "It wasn't to my taste"})
        self.assertEqual(by_en["I'm swamped"]["count"], 3)
        self.assertEqual(by_en["I'm swamped"]["last_seen"], "2026-10-20")
        self.assertEqual(by_en["I'm swamped"]["note"], "최신 노트")
        self.assertEqual((by_en["lazing around"]["count"], by_en["lazing around"]["kind"]), (2, "word"))
        self.assertEqual(by_en["It wasn't to my taste"]["count"], 1)
        self.assertEqual([g["count"] for g in merged], [3, 2, 1])  # count 내림차순

    def test_merge_sorts_ties_by_recency_and_caps_at_eight(self):
        old = [gap(f"한{i}", f"en{i}", count=1, last_seen=f"2026-10-{10 + i:02d}") for i in range(8)]
        merged = lp.merge_thinking_gaps(old, [tgap("새것", "brand new")], "2026-10-20")
        self.assertEqual(len(merged), 8)
        self.assertEqual(merged[0]["english"], "brand new")  # count 1 동률 -> 가장 최근
        self.assertNotIn("en0", [g["english"] for g in merged])  # 가장 오래된 것이 탈락

    def test_update_profile_merges_in_code_and_ignores_model_value(self):
        self.path.write_text(json.dumps(card(thinking_gaps=[gap("정신없다", "I'm swamped", count=2)])), encoding="utf-8")
        model = card(thinking_gaps=[gap("조작", "fake", count=99)])
        tutoring = {"thinking_gaps": [tgap("정신없다", "I'm swamped"), tgap("빈둥빈둥", "lazing around", kind="word")]}

        ok = lp.update_profile(tutoring, generate_text=lambda p: json.dumps(model), path=self.path, now=NOW)

        self.assertTrue(ok)
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual([(g["english"], g["count"]) for g in saved["thinking_gaps"]], [("I'm swamped", 3), ("lazing around", 1)])
        self.assertEqual(saved["thinking_gaps"][0]["last_seen"], "2026-10-20")

    def test_merge_protects_touched_items_from_cap(self):
        old = [gap(f"한{i}", f"en{i}", count=3) for i in range(8)]
        merged = lp.merge_thinking_gaps(old, [tgap("새것", "brand new")], "2026-10-20")
        self.assertEqual(len(merged), 8)
        self.assertIn("brand new", [g["english"] for g in merged])
        self.assertEqual(sum(1 for g in merged if g["english"].startswith("en")), 7)

    def test_merge_kind_sticks_to_framing(self):
        old = [gap("정신없다", "swamped", kind="framing"), gap("빈둥", "lazing", kind="word")]
        merged = lp.merge_thinking_gaps(old, [tgap("정신없다", "swamped", kind="word"), tgap("빈둥", "lazing", kind="framing")], "2026-10-20")
        self.assertEqual({g["english"]: g["kind"] for g in merged}, {"swamped": "framing", "lazing": "framing"})

    def test_update_profile_model_failure_still_merges_gaps(self):
        self.path.write_text(json.dumps(card(thinking_gaps=[gap("정신없다", "I'm swamped", count=2)])), encoding="utf-8")
        tutoring = {"thinking_gaps": [tgap("정신없다", "I'm swamped"), tgap("빈둥빈둥", "lazing around", kind="word")]}

        def boom(_prompt):
            raise RuntimeError("model down")

        for generate in (boom, lambda p: "not json", lambda p: json.dumps({"bad": 1})):
            self.path.write_text(json.dumps(card(thinking_gaps=[gap("정신없다", "I'm swamped", count=2)])), encoding="utf-8")
            with self.assertLogs(lp.logger, level="ERROR"):
                ok = lp.update_profile(tutoring, generate_text=generate, path=self.path, now=NOW)
            self.assertTrue(ok)
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.assertEqual([(g["english"], g["count"]) for g in saved["thinking_gaps"]], [("I'm swamped", 3), ("lazing around", 1)])
            self.assertEqual(saved["level"], LEVEL)
            self.assertEqual(saved["weak_points"][0]["pattern"], "past tense")
            self.assertTrue(saved["updated"].startswith("2026-10-20"))
        self.assertTrue(any(lp.get_history_dir(self.path).iterdir()))

    def test_update_profile_returns_false_when_write_fails(self):
        with mock.patch.object(lp, "_write_atomic", side_effect=OSError("disk")):
            with self.assertLogs(lp.logger, level="ERROR"):
                ok = lp.update_profile({"thinking_gaps": [tgap("가", "go")]}, generate_text=lambda p: 1 / 0, path=self.path, now=NOW)
        self.assertFalse(ok)

    def test_brief_lists_up_to_three_framing_first(self):
        gaps = [
            gap("빈둥빈둥", "lazing around", kind="word", count=9),
            gap("정신없다", "swamped", count=3),
            gap("입맛에 안 맞다", "It wasn't to my taste", count=2),
            gap("아쉽다", "bummer", count=1),
            gap("단어", "word only", kind="word", count=1),
        ]
        brief = lp.profile_brief(lp.validate_profile(card(thinking_gaps=gaps)))

        line = next(s for s in brief.split(". ") if lp.RECYCLE_PREFIX in s)
        self.assertEqual(line.rstrip("."), lp.RECYCLE_PREFIX + "'swamped', 'It wasn't to my taste', 'bummer'")
        self.assertFalse(re.search(r"[\uac00-\ud7a3]", brief))
        self.assertNotIn("lazing around", brief)  # framing 3개가 이미 찬다
        self.assertLessEqual(len(brief), lp.BRIEF_MAX_CHARS)

    def test_brief_without_gaps_has_no_gap_line(self):
        self.assertNotIn("Expressions to recycle", lp.profile_brief(lp.validate_profile(card())))


if __name__ == "__main__":
    unittest.main()

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import learner_profile as lp
from server import main, tutor


def tgap(korean, english, kind="framing", note="새 노트"):
    return {"korean": korean, "english": english, "kind": kind, "note": note}


class TutorNormalizeTest(unittest.TestCase):
    def test_normalize_thinking_gaps_in_tutor_module(self):
        raw = {
            "thinking_gaps": [
                tgap(" 정신없다 ", "I'm swamped", kind="Framing"),
                tgap("x", "y", kind="grammar"),
                tgap("가" * 100, "e" * 200, kind="word"),
            ]
        }
        out = tutor.normalize_tutor_json(raw)["thinking_gaps"]
        self.assertEqual([g["kind"] for g in out], ["framing", "word"])
        self.assertEqual(out[0]["korean"], "정신없다")
        self.assertEqual((len(out[1]["korean"]), len(out[1]["english"])), (tutor.MAX_GAP_KOREAN, tutor.MAX_GAP_ENGLISH))
        self.assertNotIn("thinking_gaps", tutor.normalize_teachback_json(raw))
        self.assertTrue(tutor.is_empty_result(tutor.normalize_tutor_json(raw)))

    def test_normalize_topic_keywords_in_tutor_module(self):
        raw = {"topic_keywords": [" Cutting-Board! ", "talk", "Small Talk", "Kitchen", "kitchen", "x" * 31, 5, "busy week", "a", "b", "c"]}
        out = tutor.normalize_tutor_json(raw)["topic_keywords"]
        self.assertEqual(out, ["cutting board", "kitchen", "busy week", "a", "b"])
        self.assertEqual(tutor.normalize_tutor_json({})["topic_keywords"], [])
        self.assertNotIn("topic_keywords", tutor.normalize_teachback_json(raw))

    def test_gap_kinds_match_learner_profile(self):
        self.assertEqual(tutor.GAP_KINDS, lp.GAP_KINDS)


class CultureTermsTest(unittest.TestCase):
    def test_shared_generic_set_and_fallback_cap(self):
        self.assertIs(main.GENERIC_TOPIC_WORDS, tutor.GENERIC_TOPIC_WORDS)
        terms = main._culture_terms({
            "topic_keywords": ["cutting board", "the day"],
            "clip_query": "kitchen knife sharpening stone granite",
            "vocab": [{"word": "whisk"}],
        })
        self.assertEqual(terms, ["cutting board", "kitchen", "knife", "sharpening"])

    def test_total_cap_is_six(self):
        kws = ["alpha one", "beta two", "gamma three", "delta four", "epsilon five"]
        terms = main._culture_terms({"topic_keywords": kws, "clip_query": "zeta eta theta iota"})
        self.assertEqual(len(terms), 6)
        self.assertEqual(terms[:5], kws)

    def test_recycle_brief_line_has_no_korean(self):
        gaps = [
            {"korean": "정신없다", "english": "I'm swamped", "kind": "framing", "note": "n", "count": 3, "last_seen": "2026-10-20"},
            {"korean": "도마", "english": "cutting board", "kind": "word", "note": "n", "count": 1, "last_seen": "2026-10-20"},
        ]
        card = lp.empty_profile()
        card["thinking_gaps"] = gaps
        brief = lp.profile_brief(card)
        line = brief[brief.index(lp.RECYCLE_PREFIX):]
        self.assertTrue(brief.startswith(lp.RECYCLE_PREFIX) or lp.RECYCLE_PREFIX in brief)
        self.assertIn("'I'm swamped'", line)
        self.assertIn("cutting board", line)
        self.assertFalse(any("\uac00" <= ch <= "\ud7a3" for ch in line))


if __name__ == "__main__":
    unittest.main()

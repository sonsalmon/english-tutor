import json
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


def fm(phrases, opening="Fun chat today!", next_time="Next time, try telling me about your week."):
    return {"opening": opening, "phrases": phrases, "next_time": next_time}


def fphrase(phrase, note="a short note"):
    return {"phrase": phrase, "note": note}


class FriendMessageTest(unittest.TestCase):
    def test_normalize_caps_and_drops_empty(self):
        raw = fm(
            [fphrase("p" * 100, "n" * 200), fphrase(""), "junk", fphrase("  I'm swamped  ", " busy ")]
            + [fphrase(f"phrase {i}") for i in range(8)],
            opening="  Fun chat today!  ",
        )
        out = tutor.normalize_tutor_json({"friend_message": raw})["friend_message"]
        self.assertEqual(out["opening"], "Fun chat today!")
        self.assertEqual(len(out["phrases"]), tutor.MAX_FRIEND_PHRASES)
        self.assertEqual(len(out["phrases"][0]["phrase"]), tutor.MAX_FRIEND_PHRASE)
        self.assertEqual(len(out["phrases"][0]["note"]), tutor.MAX_FRIEND_NOTE)
        self.assertEqual(out["phrases"][1], {"phrase": "I'm swamped", "note": "busy"})
        self.assertEqual(set(out), {"opening", "phrases", "next_time"})

    def test_missing_or_unusable_is_none(self):
        self.assertIsNone(tutor.normalize_tutor_json({})["friend_message"])
        for bad in (None, "hi", [], {}, fm([]), fm([fphrase(""), "x"]), {"phrases": "nope"}):
            self.assertIsNone(tutor.normalize_friend_message(bad), bad)

    def test_missing_opening_and_next_time_become_empty_strings(self):
        out = tutor.normalize_friend_message({"phrases": [fphrase("cutting board")]})
        self.assertEqual((out["opening"], out["next_time"]), ("", ""))

    def test_friend_message_alone_does_not_make_result_non_empty(self):
        out = tutor.normalize_tutor_json({"friend_message": fm([fphrase("cutting board")])})
        self.assertTrue(tutor.is_empty_result(out))

    def test_teachback_has_no_friend_message(self):
        raw = {"friend_message": fm([fphrase("cutting board")]), "good": [{"said": "a", "note": "b"}]}
        self.assertNotIn("friend_message", tutor.normalize_teachback_json(raw))

    def test_partner_name_from_transcript_meta(self):
        self.assertEqual(tutor.partner_name_of("# Call\n- partner: priya\n- duration: 1m\n"), "Priya")
        self.assertEqual(tutor.partner_name_of("# Call\n- mission: x\n"), "Ms. Park")
        self.assertEqual(tutor.partner_name_of("- partner: nobody\n"), "Ms. Park")
        # 줄 맨 앞에서 시작하는 메타 줄만 인정한다(대화 안의 비슷한 문장은 무시).
        self.assertEqual(tutor.partner_name_of("**Me:** - partner: omar\n"), "Ms. Park")

    def test_prompt_names_the_partner_and_asks_for_the_contract(self):
        prompt = tutor.build_prompt("# Call\n- partner: omar\n**Me:** hi\n")
        self.assertIn("Omar, the call partner", prompt)
        self.assertIn('"friend_message"', prompt)
        self.assertIn("Ms. Park, the call partner", tutor.build_prompt("**Me:** hi\n"))

    def test_prompt_gives_no_copyable_opening_example(self):
        prompt = tutor.build_prompt("**Me:** hi\n")
        self.assertNotIn("Fun chat today!", prompt)
        self.assertIn('"friend_message"', prompt)

    def test_analyze_transcript_returns_friend_message(self):
        reply = json.dumps({"good": [{"said": "a", "note": "b"}], "friend_message": fm([fphrase("cutting board")])})
        out = tutor.analyze_transcript("**Me:** hi", generate_text=lambda _p: reply)
        self.assertEqual(out["friend_message"]["phrases"][0]["phrase"], "cutting board")
        reply_without = json.dumps({"good": [{"said": "a", "note": "b"}]})
        self.assertIsNone(tutor.analyze_transcript("**Me:** hi", generate_text=lambda _p: reply_without)["friend_message"])


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

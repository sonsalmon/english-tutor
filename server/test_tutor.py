import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import known
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

    TRANSCRIPT = (
        "# Call\n- partner: priya\n\n"
        "**Me:** Yesterday I go to the farmers market and buy fresh tomatoes.\n"
        "**Partner:** Oh nice! You went to the farmers market, that sounds fun.\n"
    )

    def test_phrase_not_in_transcript_is_dropped(self):
        raw = fm([fphrase("quantum entanglement is spooky"), fphrase("went to the farmers market"), fphrase("buy fresh tomatoes")])
        out = tutor.normalize_friend_message(raw, self.TRANSCRIPT)
        self.assertEqual([p["phrase"] for p in out["phrases"]], ["went to the farmers market", "buy fresh tomatoes"])

    def test_natural_fix_built_from_transcript_words_stays(self):
        raw = fm([fphrase("I bought fresh tomatoes at the farmers market")])  # bought는 전문에 없지만 나머지 단어가 있다
        out = tutor.normalize_friend_message(raw, self.TRANSCRIPT)
        self.assertEqual(len(out["phrases"]), 1)

    def test_all_phrases_invented_gives_none_and_notes_are_not_checked(self):
        self.assertIsNone(tutor.normalize_friend_message(fm([fphrase("space shuttle launch", "farmers market tomatoes")]), self.TRANSCRIPT))

    def test_header_and_other_lines_do_not_count_as_spoken(self):
        # "priya"는 머리글에만 있다 -> Me·Partner 줄이 아니므로 근거가 되지 않는다
        self.assertIsNone(tutor.normalize_friend_message(fm([fphrase("priya partner call")]), self.TRANSCRIPT))

    def test_normalize_tutor_json_and_analyze_pass_the_transcript(self):
        raw = {"corrections": [{"said": "a", "better": "b", "why": "c"}], "friend_message": fm([fphrase("space shuttle launch"), fphrase("farmers market")])}
        out = tutor.normalize_tutor_json(raw, self.TRANSCRIPT)
        self.assertEqual([p["phrase"] for p in out["friend_message"]["phrases"]], ["farmers market"])
        got = tutor.analyze_transcript(self.TRANSCRIPT, generate_text=lambda _p: json.dumps(raw))
        self.assertEqual([p["phrase"] for p in got["friend_message"]["phrases"]], ["farmers market"])

    def test_profile_update_prompt_excludes_friend_message(self):
        tutoring = {"corrections": [{"said": "x", "better": "y", "why": "z"}], "friend_message": fm([fphrase("zebra crossing")])}
        prompt = lp.build_update_prompt({"level": "B1"}, tutoring, "2026-10-20")
        self.assertNotIn("friend_message", prompt)
        self.assertNotIn("zebra crossing", prompt)
        self.assertIn('"corrections"', prompt)
        self.assertIn("friend_message", tutoring)  # 원본 dict는 그대로

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
        out = tutor.analyze_transcript("**Me:** I bought a cutting board", generate_text=lambda _p: reply)
        self.assertEqual(out["friend_message"]["phrases"][0]["phrase"], "cutting board")
        reply_without = json.dumps({"good": [{"said": "a", "note": "b"}]})
        self.assertIsNone(tutor.analyze_transcript("**Me:** hi", generate_text=lambda _p: reply_without)["friend_message"])


US_TRANSCRIPT = (
    "# Call\n- partner: jake\n\n"
    "**Partner:** Hey! How was your day?\n"
    "**Me:** How old are you?\n"
    "**Partner:** Ha, I'm 27.\n"
    "**Me:** Sorry?\n"
    "**Me:** I'm sorry for your trouble.\n"
    "**Me:** I think it is good idea.\n"
)


def us(said, natural, why="영어권의 사고방식이 달라요.", korean_way="한국어로 생각했어요"):
    return {"said": said, "korean_way": korean_way, "natural": natural, "why": why}


class UsStyleTest(unittest.TestCase):
    def norm(self, rows, **kw):
        return tutor.normalize_us_style(rows, US_TRANSCRIPT, **kw)

    def test_a_good_item_stays_with_all_four_fields(self):
        out = self.norm([us("How old are you?", "So, what do you do?")])

        self.assertEqual(len(out), 1)
        self.assertEqual(set(out[0]), {"said", "korean_way", "natural", "why"})
        self.assertEqual(out[0]["natural"], "So, what do you do?")

    def test_said_that_is_not_in_the_transcript_is_dropped(self):
        out = self.norm([us("Please forgive my rudeness", "Sorry about that"), us("How old are you?", "So, what do you do?")])

        self.assertEqual([r["said"] for r in out], ["How old are you?"])

    def test_said_overlapping_one_me_line_by_seventy_percent_counts(self):
        # 7 of 10 words of the quote are in one Me line, 3 are not
        out = self.norm([us("I think it is good idea for us all to go", "Sounds like a plan")])
        self.assertEqual(out, [])
        out = self.norm([us("I think it is good idea", "Sounds like a plan")])
        self.assertEqual(len(out), 1)

    def test_said_found_only_in_the_raw_verbatim_is_accepted_when_it_is_given(self):
        row = us("Could you pass me the salt", "Mind passing the salt?")
        self.assertEqual(self.norm([row]), [])
        self.assertEqual(len(self.norm([row], verbatim="um could you pass me the salt\nokay")), 1)

    def test_natural_the_learner_already_said_is_dropped(self):
        out = self.norm([us("How old are you?", "Sorry?"), us("How old are you?", "So, what do you do?")])

        self.assertEqual([r["natural"] for r in out], ["So, what do you do?"])

    def test_natural_mostly_made_of_words_from_one_me_line_is_dropped(self):
        out = self.norm([us("How old are you?", "I'm sorry for your trouble")])

        self.assertEqual(out, [])

    def test_natural_in_the_known_store_or_inside_a_known_phrase_is_dropped(self):
        rows = [us("How old are you?", "Thanks for jumping on this"), us("How old are you?", "So, what do you do?")]

        self.assertEqual(len(self.norm(rows, known=["Thanks for jumping on this!"])), 1)
        self.assertEqual(len(self.norm(rows, known=["jumping on this"])), 1)
        self.assertEqual(len(self.norm(rows, known=[])), 2)

    def test_natural_equal_to_a_thinking_gap_is_left_to_thinking_gaps(self):
        out = self.norm([us("How old are you?", "I'm swamped")], gap_english=["I'm swamped"])

        self.assertEqual(out, [])

    def test_empty_fields_non_dicts_and_duplicates_are_dropped_and_the_list_is_capped_at_three(self):
        rows = [us("How old are you?", "So, what do you do?"), us("How old are you?", "so what do you do"), "junk", us("", "x y"), us("How old are you?", ""), us("How old are you?", "natural one", why="")]
        rows += [us("How old are you?", f"natural phrase number {n}") for n in ("one", "two", "three", "four")]

        out = self.norm(rows)

        self.assertEqual(len(out), tutor.MAX_US_STYLE)
        self.assertEqual(out[0]["natural"], "So, what do you do?")

    def test_overlong_fields_are_cut_and_overlong_natural_is_dropped(self):
        long_why = us("How old are you?", "So, what do you do?", why="x" * 1000)
        too_many_words = us("How old are you?", " ".join(f"word{c}" for c in "abcdefghijk"))

        out = self.norm([long_why, too_many_words])

        self.assertEqual(len(out), 1)
        self.assertEqual(len(out[0]["why"]), tutor.MAX_US_WHY)

    def test_without_a_transcript_only_the_shape_and_known_checks_run(self):
        out = tutor.normalize_us_style([us("anything", "Mind passing the salt?")])

        self.assertEqual(len(out), 1)
        self.assertEqual(tutor.normalize_us_style("junk"), [])

    def test_normalize_tutor_json_forces_pragmatics_empty_and_filters_us_style(self):
        raw = {
            "pragmatics": [{"pattern": "Bottom line first", "note": "n"}],
            "us_style": [us("How old are you?", "So, what do you do?"), us("How old are you?", "Sorry?")],
            "thinking_gaps": [{"korean": "x", "english": "I'm swamped", "kind": "framing", "note": "n"}],
            "good": [{"said": "a", "note": "b"}],
        }

        out = tutor.normalize_tutor_json(raw, US_TRANSCRIPT)

        self.assertEqual(out["pragmatics"], [])
        self.assertEqual([r["natural"] for r in out["us_style"]], ["So, what do you do?"])

    def test_known_expressions_leave_corrections_vocab_and_us_style(self):
        raw = {
            "corrections": [{"said": "a", "better": "I just started", "why": "x"}, {"said": "b", "better": "I got swamped", "why": "y"}],
            "vocab": [{"word": "circle back", "meaning_ko": "m", "example": "e", "etymology": ""}, {"word": "swamped", "meaning_ko": "m", "example": "e", "etymology": ""}],
            "good": [{"said": "a", "note": "b"}],
        }

        out = tutor.normalize_tutor_json(raw, known=["i just started", "Circle back."])

        self.assertEqual([c["better"] for c in out["corrections"]], ["I got swamped"])
        self.assertEqual([v["word"] for v in out["vocab"]], ["swamped"])

    def test_us_style_alone_makes_the_result_non_empty_and_old_pragmatics_still_count(self):
        self.assertFalse(tutor.is_empty_result({"us_style": [us("a", "b c")]}))
        self.assertFalse(tutor.is_empty_result({"pragmatics": [{"pattern": "p", "note": "n"}]}))
        self.assertTrue(tutor.is_empty_result({"us_style": [], "pragmatics": []}))

    def test_teachback_keeps_its_pragmatics_and_has_no_us_style(self):
        raw = {"pragmatics": [{"pattern": "Check understanding", "note": "n"}], "us_style": [us("a b", "c d")], "good": [{"said": "a", "note": "b"}]}

        out = tutor.normalize_teachback_json(raw)

        self.assertEqual(out["pragmatics"], [{"pattern": "Check understanding", "note": "n"}])
        self.assertNotIn("us_style", out)

    def test_prompt_asks_for_us_style_and_known_expressions_are_appended_only_when_given(self):
        prompt = tutor.build_prompt(US_TRANSCRIPT)

        self.assertIn('"us_style"', prompt)
        self.assertNotIn("ALREADY KNOWN (", prompt)
        self.assertEqual(tutor.with_known(prompt, []), prompt)
        appended = tutor.with_known(prompt, ["circle back", "Sorry?"])
        self.assertTrue(appended.startswith(prompt))
        self.assertIn("ALREADY KNOWN (", appended)
        self.assertTrue(appended.endswith("circle back | Sorry?"))

    def test_analyze_transcript_passes_known_to_the_prompt_and_the_filter(self):
        seen = []
        reply = json.dumps(
            {
                "corrections": [{"said": "a", "better": "I just started", "why": "x"}, {"said": "b", "better": "I got swamped", "why": "y"}],
                "us_style": [us("How old are you?", "So, what do you do?"), us("How old are you?", "Sorry?")],
            }
        )

        def generate(prompt):
            seen.append(prompt)
            return reply

        out = tutor.analyze_transcript(US_TRANSCRIPT, generate_text=generate, known=["I just started"])

        self.assertIn("ALREADY KNOWN (", seen[0])
        self.assertEqual([c["better"] for c in out["corrections"]], ["I got swamped"])
        self.assertEqual([r["natural"] for r in out["us_style"]], ["So, what do you do?"])

    def test_run_tutoring_reads_the_store_unless_known_is_given(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        path = root / "2026-10-20-090000.md"
        path.write_text(US_TRANSCRIPT, encoding="utf-8")
        reply = json.dumps({"corrections": [{"said": "a", "better": "I just started", "why": "x"}, {"said": "b", "better": "I got swamped", "why": "y"}]})
        env = {"TUTORING_DIR": str(root / "tutoring"), "AUDIO_DIR": str(root / "audio"), "KNOWN_EXPRESSIONS_PATH": str(root / "known.json")}
        with mock.patch.dict("os.environ", env), mock.patch("server.learner_profile.load_profile", return_value=None):
            known.add("I just started", "known", "s")
            data, saved = tutor.run_tutoring(path, generate_text=lambda _p: reply)
            everything, _ = tutor.run_tutoring(path, generate_text=lambda _p: reply, known=[])

        self.assertTrue(saved)
        self.assertEqual([c["better"] for c in data["corrections"]], ["I got swamped"])
        self.assertEqual(len(everything["corrections"]), 2)


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

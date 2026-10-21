import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import culture_filter as cf

WORK_CALL = {
    "topic_keywords": ["performance review", "deadline"],
    "thinking_gaps": [{"korean": "x", "english": "I'm swamped", "kind": "framing", "note": "n"}],
}


def bank(topic, context, text, country="US"):
    return {"country": country, "topic": topic, "context": context, "text": text, "source": "reddit"}


def blend(question, bid="b"):
    return {"id": bid, "question": question, "korea": ["a"], "us": ["b"]}


class AnchorTermsTest(unittest.TestCase):
    def test_terms_come_only_from_topic_keywords_and_thinking_gaps(self):
        terms = cf.anchor_terms({**WORK_CALL, "clip_query": "coworkers at the beach", "vocab": [{"word": "swimwear"}]})

        self.assertEqual(terms, [cf.stems_of("performance review"), cf.stems_of("deadline"), cf.stems_of("swamped")])

    def test_generic_words_and_junk_make_no_terms(self):
        self.assertEqual(cf.anchor_terms({"topic_keywords": ["talk", "the day"], "thinking_gaps": ["junk", {"english": None}]}), [])
        self.assertEqual(cf.anchor_terms({"topic_keywords": "junk"}), [])
        self.assertEqual(cf.anchor_terms({}), [])

    def test_suffixes_are_ignored_so_plural_and_ing_forms_match(self):
        self.assertEqual(cf.stems_of("deadlines"), cf.stems_of("deadline"))
        self.assertEqual(cf.stems_of("reviewing reviewed"), cf.stems_of("review"))


class FilterFoundTest(unittest.TestCase):
    def test_the_beach_swimwear_note_is_dropped_for_a_work_call(self):
        found = {
            "blend": [blend("What do people wear at the beach?")],
            "bank": [bank("swimwear", "beach", "Americans wear swimwear at the beach.")],
        }

        self.assertEqual(cf.filter_found(found, WORK_CALL), {"blend": [], "bank": []})

    def test_notes_about_the_call_topic_stay(self):
        on_topic = bank("performance review", "workplace", "Americans expect direct feedback in a performance review.")
        found = {"blend": [blend("How do people handle a deadline at work?")], "bank": [on_topic, bank("swimwear", "beach", "Beach clothes.")]}

        out = cf.filter_found(found, WORK_CALL)

        self.assertEqual([b["id"] for b in out["blend"]], ["b"])
        self.assertEqual(out["bank"], [on_topic])

    def test_a_single_keyword_only_in_the_body_is_not_strong_enough(self):
        note = bank("tipping", "restaurant", "Servers rarely care about a deadline.")

        self.assertEqual(cf.filter_found({"blend": [], "bank": [note]}, WORK_CALL)["bank"], [])

    def test_two_different_keywords_in_the_body_are_strong_enough(self):
        note = bank("workplace", "office", "Every deadline feels swamped for new hires.")

        self.assertEqual(cf.filter_found({"blend": [], "bank": [note]}, WORK_CALL)["bank"], [note])

    def test_a_keyword_phrase_needs_all_its_words(self):
        note = bank("workplace", "office", "A review of the menu.")

        self.assertEqual(cf.filter_found({"blend": [], "bank": [note]}, {"topic_keywords": ["performance review"]})["bank"], [])
        self.assertEqual(cf.filter_found({"blend": [], "bank": [note]}, {"topic_keywords": ["menu review"]})["bank"], [note])

    def test_no_anchor_terms_hides_everything(self):
        found = {"blend": [blend("What do people eat for breakfast?")], "bank": [bank("food", "home", "People eat rice.")]}

        self.assertEqual(cf.filter_found(found, {"clip_query": "breakfast rice"}), {"blend": [], "bank": []})

    def test_results_are_capped_at_three_blend_and_two_bank_per_country(self):
        found = {
            "blend": [blend(f"What is a deadline number {n}?", bid=str(n)) for n in range(6)],
            "bank": [bank("deadline", "work", f"US note {n}", "US") for n in range(4)] + [bank("deadline", "work", f"KR note {n}", "KR") for n in range(4)],
        }

        out = cf.filter_found(found, WORK_CALL)

        self.assertEqual(len(out["blend"]), cf.MAX_BLEND)
        self.assertEqual([b["country"] for b in out["bank"]], ["US", "US", "KR", "KR"])

    def test_missing_fields_do_not_crash(self):
        out = cf.filter_found({"blend": [{"id": "x"}], "bank": [{"country": "US"}]}, WORK_CALL)

        self.assertEqual(out, {"blend": [], "bank": []})
        self.assertEqual(cf.filter_found({}, WORK_CALL), {"blend": [], "bank": []})


if __name__ == "__main__":
    unittest.main()

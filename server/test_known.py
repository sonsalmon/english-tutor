import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import known


class KnownStoreTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "known.json"

    def test_make_key_lowercases_strips_punctuation_and_collapses_spaces(self):
        self.assertEqual(known.make_key("  Sorry?! "), "sorry")
        self.assertEqual(known.make_key("I\u2019m  SO   sorry."), "i'm so sorry")
        self.assertEqual(known.make_key("\ud55c\uad6d\uc5b4"), "")
        self.assertEqual(known.make_key(None), "")

    def test_add_persists_and_moves_the_same_key_to_the_end_with_the_new_state(self):
        self.assertTrue(known.add("Sorry?", "known", "2026-10-20-090000", path=self.path))
        known.add("circle back", "known", "2026-10-20-090000", path=self.path)
        known.add("sorry", "misheard", "2026-10-21-090000", path=self.path)

        entries = known.load(self.path)
        self.assertEqual([(e["key"], e["state"], e["stem"]) for e in entries], [("circle back", "known", "2026-10-20-090000"), ("sorry", "misheard", "2026-10-21-090000")])
        self.assertTrue(entries[1]["at"])

    def test_add_rejects_an_unknown_state_and_ignores_keyless_text(self):
        with self.assertRaises(ValueError):
            known.add("x y", "saved", "s", path=self.path)
        self.assertFalse(known.add("\ud55c\uad6d\uc5b4", "known", "s", path=self.path))
        self.assertEqual(known.load(self.path), [])

    def test_store_keeps_only_the_newest_500(self):
        for i in range(known.MAX_ENTRIES + 3):
            known.add(f"phrase number {i}", "known", "s", path=self.path)

        entries = known.load(self.path)
        self.assertEqual(len(entries), known.MAX_ENTRIES)
        self.assertEqual(entries[0]["key"], "phrase number 3")
        self.assertEqual(entries[-1]["key"], f"phrase number {known.MAX_ENTRIES + 2}")

    def test_remove_undoes_and_reports_whether_anything_was_removed(self):
        known.add("circle back", "known", "s", path=self.path)

        self.assertTrue(known.remove("Circle back!", path=self.path))
        self.assertFalse(known.remove("circle back", path=self.path))
        self.assertEqual(known.load(self.path), [])

    def test_backup_is_kept_when_the_file_is_rewritten(self):
        known.add("one two", "known", "s", path=self.path)
        known.add("three four", "known", "s", path=self.path)

        backup = json.loads(self.path.with_name("known.json.bak").read_text(encoding="utf-8"))
        self.assertEqual([e["key"] for e in backup], ["one two"])

    def test_missing_or_broken_file_loads_as_empty(self):
        self.assertEqual(known.load(self.path), [])
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(known.load(self.path), [])
        self.path.write_text(json.dumps([{"text": "ok phrase", "state": "known"}, {"text": "bad", "state": "weird"}, 5]), encoding="utf-8")
        self.assertEqual([e["key"] for e in known.load(self.path)], ["ok phrase"])

    def test_default_path_follows_the_sessions_folder_unless_overridden(self):
        with mock.patch.dict("os.environ", {"TRANSCRIPT_DIR": "/tmp/x/sessions"}, clear=False):
            with mock.patch.dict("os.environ", {}, clear=False):
                import os

                os.environ.pop(known.KNOWN_PATH_ENV, None)
                self.assertEqual(known.get_known_path(), Path("/tmp/x/known-expressions.json"))
            with mock.patch.dict("os.environ", {known.KNOWN_PATH_ENV: "/tmp/y/k.json"}):
                self.assertEqual(known.get_known_path(), Path("/tmp/y/k.json"))


class IsKnownTest(unittest.TestCase):
    def test_equal_keys_and_short_phrase_containment_both_ways(self):
        keys = known.keys_of(["Thanks for jumping on this", "sorry"])

        self.assertTrue(known.is_known("thanks for jumping on this!", keys))
        self.assertTrue(known.is_known("Thanks for jumping on this one", keys))
        self.assertTrue(known.is_known("jumping on this", keys))
        self.assertTrue(known.is_known("sorry?", keys))

    def test_a_single_known_word_does_not_swallow_longer_phrases(self):
        keys = known.keys_of(["sorry"])

        self.assertFalse(known.is_known("Sorry, could you repeat that?", keys))
        self.assertFalse(known.is_known("", keys))
        self.assertFalse(known.is_known("circle back", keys))

    def test_long_phrases_are_not_matched_by_containment(self):
        keys = known.keys_of(["a b c d e f g h"])

        self.assertFalse(known.is_known("a b c d e f g", keys))
        self.assertTrue(known.is_known("b c d e f", keys))
        self.assertTrue(known.is_known("a b c d e f g h", keys))


class PromptBlockTest(unittest.TestCase):
    def test_empty_list_adds_nothing_and_long_list_keeps_the_newest_sixty(self):
        self.assertEqual(known.prompt_block([]), "")
        block = known.prompt_block([f"phrase {i}" for i in range(known.PROMPT_RECENT + 5)])

        self.assertIn("ALREADY KNOWN", block)
        self.assertNotIn("phrase 4 |", block)
        self.assertIn("phrase 5 |", block)
        self.assertTrue(block.endswith(f"phrase {known.PROMPT_RECENT + 4}"))

    def test_each_expression_is_cut_to_the_prompt_limit(self):
        block = known.prompt_block(["x" * 500])

        self.assertLessEqual(block.count("x"), known.PROMPT_TEXT)


class AnalysisExpressionsTest(unittest.TestCase):
    def test_card_phrases_and_fixed_points_come_before_the_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "known.json"
        known.add("Sorry?", "known", "s", path=path)
        card = {"phrases": [{"phrase": "circle back"}], "fixed_points": [{"pattern": "past tense"}]}

        with mock.patch("server.learner_profile.load_profile", return_value=card):
            self.assertEqual(known.analysis_expressions(path), ["circle back", "past tense", "Sorry?"])

    def test_unreadable_card_still_gives_the_store(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "known.json"
        known.add("Sorry?", "known", "s", path=path)

        with mock.patch("server.learner_profile.load_profile", side_effect=RuntimeError("broken")):
            self.assertEqual(known.analysis_expressions(path), ["Sorry?"])


if __name__ == "__main__":
    unittest.main()

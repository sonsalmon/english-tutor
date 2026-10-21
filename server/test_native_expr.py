import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import embeds, feed, known, native_expr


def allow_all(ids):
    return set(ids)


def raw(expression, per_million=10.0, kind="phrasal_verb", register="casual", videos=("a", "b")):
    return {
        "expression": expression,
        "kind": kind,
        "meaning_ko": "뜻",
        "why_hard": "이유",
        "register": register,
        "example": "An example.",
        "per_million": per_million,
        "count": 10,
        "clips": [
            {"video_id": f"{expression.replace(' ', '')}-{v}", "start": 3.0, "end": 7.0, "text": f"we {expression} now", "title": "T", "channel": "C"}
            for v in videos
        ],
    }


def entries_of(*items):
    return [e for e in (native_expr.clean_entry(i) for i in items) if e]


class LemmaTest(unittest.TestCase):
    def test_inflections_merge(self):
        pairs = [
            ("ended up", "end up"),
            ("figured out", "figure out"),
            ("figuring out", "figure out"),
            ("came up with", "come up with"),
            ("making sense", "make sense"),
            ("takes care", "take care"),
            ("running late", "run late"),
            ("kicked in", "kick in"),
        ]
        for surface, base in pairs:
            self.assertEqual(native_expr.lemma_key(surface), native_expr.lemma_key(base), surface)

    def test_curly_apostrophe_and_case(self):
        self.assertEqual(native_expr.lemma_key("It\u2019s FINE"), native_expr.lemma_key("it's fine"))

    def test_short_and_contraction_tokens_stay(self):
        self.assertEqual(native_expr.lemma_token("don't"), "don't")
        self.assertEqual(native_expr.lemma_token("bus"), "bus")
        self.assertEqual(native_expr.lemma_token("class"), "class")


class LoadTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "native.json"

    def test_missing_file_is_empty(self):
        self.assertEqual(native_expr.load(self.path), [])

    def test_broken_json_is_empty(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(native_expr.load(self.path), [])

    def test_bad_entries_are_skipped_and_wrapper_is_read(self):
        good = raw("figure out")
        no_clips = {**raw("end up"), "clips": []}
        bad_kind = {**raw("touch base"), "kind": "literal"}
        no_meaning = {**raw("call it a day"), "meaning_ko": ""}
        self.path.write_text(json.dumps({"expressions": [good, no_clips, bad_kind, no_meaning, "x", None]}), encoding="utf-8")
        loaded = native_expr.load(self.path)
        self.assertEqual([e["expression"] for e in loaded], ["figure out"])
        self.assertEqual(loaded[0]["key"], "figure out")

    def test_list_file_and_reload_after_change(self):
        self.path.write_text(json.dumps([raw("figure out")]), encoding="utf-8")
        self.assertEqual(len(native_expr.load(self.path)), 1)
        self.path.write_text(json.dumps([raw("figure out"), raw("end up")]), encoding="utf-8")
        self.assertEqual(len(native_expr.load(self.path)), 2)

    def test_env_path_override(self):
        with mock.patch.dict(os.environ, {native_expr.PATH_ENV: str(self.path)}):
            self.assertEqual(native_expr.native_path(), self.path)

    def test_clips_are_capped_at_three(self):
        entry = native_expr.clean_entry(raw("figure out", videos=("a", "b", "c", "d", "e")))
        self.assertEqual(len(entry["clips"]), 3)


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.known = Path(self._tmp.name) / "known.json"

    def test_known_expressions_are_excluded(self):
        entries = entries_of(raw("figure out"), raw("end up"))
        known.add("figure out", "known", "s", path=self.known)
        left = native_expr.eligible(entries, self.known)
        self.assertEqual([e["expression"] for e in left], ["end up"])

    def test_known_phrase_containing_expression_excludes_it(self):
        entries = entries_of(raw("end up"), raw("touch base"))
        known.add("we always end up in the same place", "known", "s", path=self.known)
        left = native_expr.eligible(entries, self.known)
        self.assertEqual([e["expression"] for e in left], ["touch base"])

    def test_weighted_order_prefers_frequent(self):
        entries = entries_of(raw("figure out", per_million=1000.0), raw("end up", per_million=0.01))
        rng = random.Random(3)
        firsts = [native_expr.weighted_order(entries, rng)[0]["expression"] for _ in range(100)]
        self.assertGreater(firsts.count("figure out"), 90)

    def test_friend_pick_prefers_saved_unused_and_skips_used_work_known(self):
        entries = entries_of(
            raw("figure out", per_million=500.0),
            raw("end up", per_million=400.0),
            raw("touch base", per_million=300.0, register="work"),
            raw("no big deal", per_million=200.0),
            raw("call it a day", per_million=100.0),
        )
        known.add("call it a day", "known", "s", path=self.known)
        picks = native_expr.pick_for_friend(
            entries,
            saved_phrases=["no big deal"],
            learner_text="I figured out the answer",
            rng=random.Random(1),
            known_path=self.known,
        )
        phrases = [p["phrase"] for p in picks]
        self.assertEqual(len(picks), 2)
        self.assertEqual(phrases[0], "no big deal")
        self.assertEqual(phrases[1], "end up")
        for banned in ("figure out", "touch base", "call it a day"):
            self.assertNotIn(banned, phrases)
        self.assertEqual(set(picks[0]), {"phrase", "meaning"})

    def test_friend_pick_with_empty_list(self):
        self.assertEqual(native_expr.pick_for_friend([], [], ""), [])

    def test_recent_learner_text_reads_only_learner_lines(self):
        folder = Path(self._tmp.name)
        (folder / "2026-10-20-100000.md").write_text("**Partner:** hello there\n**Me:** I ended up late\n", encoding="utf-8")
        text = native_expr.recent_learner_text(folder)
        self.assertIn("ended up late", text)
        self.assertNotIn("hello there", text)


class FeedSourceTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.known = Path(self._tmp.name) / "known.json"
        self.entries = entries_of(raw("figure out", 50.0), raw("end up", 40.0), raw("touch base", 30.0))

    def test_card_shape_and_one_clip_per_expression(self):
        cards = feed.build_native_page(self.entries, 10, set(), rng=random.Random(1), known_path=self.known)
        self.assertEqual(len(cards), 3)
        self.assertEqual({c["term"] for c in cards}, {"figure out", "end up", "touch base"})
        card = cards[0]
        self.assertEqual(card["source"], "native")
        self.assertEqual(set(card["native"]), {"expression", "kind", "meaning_ko", "why_hard", "register", "example", "per_million"})
        self.assertEqual(len({c["video_id"] for c in cards}), 3)

    def test_seen_clips_are_not_repeated(self):
        first = feed.build_native_page(self.entries, 10, set(), rng=random.Random(2), known_path=self.known)
        seen = {c["id"] for c in first}
        second = feed.build_native_page(self.entries, 10, seen, rng=random.Random(2), known_path=self.known)
        self.assertEqual(len(second), 3)
        self.assertFalse(seen & {c["id"] for c in second})
        third = feed.build_native_page(self.entries, 10, seen | {c["id"] for c in second}, rng=random.Random(2), known_path=self.known)
        self.assertEqual(third, [])

    def test_limit_and_known_exclusion(self):
        known.add("end up", "known", "s", path=self.known)
        cards = feed.build_native_page(self.entries, 1, set(), rng=random.Random(1), known_path=self.known)
        self.assertEqual(len(cards), 1)
        every = feed.build_native_page(self.entries, 10, set(), rng=random.Random(1), known_path=self.known)
        self.assertNotIn("end up", {c["term"] for c in every})

    def page_env(self, path):
        return {native_expr.PATH_ENV: str(path), known.KNOWN_PATH_ENV: str(self.known), "TRANSCRIPT_DIR": self._tmp.name}

    def test_page_reads_env_file_and_reports_count(self):
        path = Path(self._tmp.name) / "native.json"
        path.write_text(json.dumps({"expressions": [raw("figure out"), raw("end up")]}), encoding="utf-8")
        with mock.patch.dict(os.environ, self.page_env(path)), mock.patch.object(embeds, "playable", allow_all):
            page = feed._page("native", 6, set())
        self.assertTrue(page["available"])
        self.assertEqual(page["native"], 2)
        self.assertEqual(len(page["clips"]), 2)

    def test_page_without_file_is_empty_not_error(self):
        with mock.patch.dict(os.environ, self.page_env(Path(self._tmp.name) / "none.json")), mock.patch.object(embeds, "playable", allow_all):
            page = feed._page("native", 6, set())
        self.assertEqual((page["clips"], page["native"]), ([], 0))
        self.assertIn("native", feed.FILTERS)

    def test_page_leaves_out_expressions_the_learner_said_in_any_old_call(self):
        folder = Path(self._tmp.name)
        (folder / "2026-01-01-000000.md").write_text("**Me:** I figured out the answer\n", encoding="utf-8")
        for day in range(2, 16):
            (folder / f"2026-01-{day:02d}-000000.md").write_text("**Me:** hello\n", encoding="utf-8")
        path = folder / "native.json"
        path.write_text(json.dumps({"expressions": [raw("figure out"), raw("end up")]}), encoding="utf-8")
        with mock.patch.dict(os.environ, self.page_env(path)), mock.patch.object(embeds, "playable", allow_all):
            page = feed._page("native", 6, set())
        self.assertEqual({c["term"] for c in page["clips"]}, {"end up"})

    def test_blocked_videos_are_never_cards_and_the_next_clip_of_the_expression_is_used(self):
        calls = []

        def playable(ids):
            calls.append(set(ids))
            return {i for i in ids if not i.endswith("-a") and not i.startswith("touchbase")}

        cards = feed.build_native_page(self.entries, 10, set(), rng=random.Random(1), known_path=self.known, playable=playable)

        self.assertEqual(len(calls), 1)
        self.assertEqual({c["term"] for c in cards}, {"figure out", "end up"})
        self.assertEqual({c["video_id"] for c in cards}, {"figureout-b", "endup-b"})


class NativeOrderTest(unittest.TestCase):
    def test_mid_frequency_idioms_and_phrasal_verbs_first_and_basics_last(self):
        entries = entries_of(
            raw("you know", 3900.0, kind="discourse_marker"),
            raw("of course", 290.0, kind="chunk"),
            raw("figure out", 120.0, kind="phrasal_verb"),
            raw("pull strings", 3.0, kind="idiom"),
            raw("kind of weird", 20.0, kind="chunk"),
            raw("rare idiom", 0.5, kind="idiom"),
        )
        for seed in range(20):
            order = [e["expression"] for e in native_expr.native_order(entries, random.Random(seed))]
            self.assertEqual(set(order[:2]), {"figure out", "pull strings"}, order)
            self.assertEqual(set(order[2:4]), {"kind of weird", "rare idiom"}, order)
            self.assertEqual(set(order[4:]), {"you know", "of course"}, order)

    def test_demotion_starts_just_above_150_per_million(self):
        entries = entries_of(raw("at the limit", 150.0, kind="idiom"), raw("over the limit", 150.5, kind="idiom"))
        self.assertEqual([native_expr.native_tier(e) for e in entries], [0, 2])

    def test_inside_the_mid_tier_the_first_card_still_varies(self):
        entries = entries_of(*[raw(f"idiom number {n}", 10.0 + 10 * n, kind="idiom") for n in range(8)])
        firsts = {native_expr.native_order(entries, random.Random(seed))[0]["expression"] for seed in range(40)}
        self.assertGreaterEqual(len(firsts), 3)

    def test_first_page_is_mid_frequency_even_when_basics_are_far_more_frequent(self):
        entries = entries_of(
            raw("you know", 3900.0, kind="discourse_marker"),
            raw("excuse me", 120.0, kind="discourse_marker"),
            raw("of course", 290.0, kind="chunk"),
            raw("figure out", 100.0, kind="phrasal_verb"),
            raw("pull strings", 3.0, kind="idiom"),
        )
        for seed in range(20):
            cards = feed.build_native_page(entries, 2, set(), rng=random.Random(seed))
            self.assertEqual({c["term"] for c in cards}, {"figure out", "pull strings"})


class LearnerNgramsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

    def test_covers_every_call_not_just_the_latest_twelve_and_only_learner_lines(self):
        (self.folder / "2026-10-01-000000.md").write_text("**Partner:** touch base\n**Me:** we ended up late\n", encoding="utf-8")
        for day in range(2, 16):
            (self.folder / f"2026-10-{day:02d}-000000.md").write_text("**Me:** hello there\n", encoding="utf-8")

        grams = native_expr.learner_ngrams(self.folder)

        self.assertIn(("end", "up"), grams)
        self.assertNotIn(("touch", "base"), grams)
        self.assertNotIn("ended up", native_expr.recent_learner_text(self.folder))

    def test_picks_up_a_new_call_after_the_files_change(self):
        self.assertNotIn(("call", "it", "a", "day"), native_expr.learner_ngrams(self.folder))
        (self.folder / "2026-10-02-000000.md").write_text("**Me:** let's call it a day\n", encoding="utf-8")
        self.assertIn(("call", "it", "a", "day"), native_expr.learner_ngrams(self.folder))

    def test_unused_by_learner_drops_inflected_uses_of_an_expression(self):
        entries = entries_of(raw("end up"), raw("touch base"))
        used = native_expr.ngrams(native_expr.lemma_tokens("We ended up late"))
        self.assertEqual([e["expression"] for e in native_expr.unused_by_learner(entries, used)], ["touch base"])


if __name__ == "__main__":
    unittest.main()

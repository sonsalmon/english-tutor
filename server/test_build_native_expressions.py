import importlib.util
import json
import random
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import clipdb  # noqa: E402

_spec = importlib.util.spec_from_file_location("build_native_expressions", ROOT / "scripts" / "build_native_expressions.py")
bne = importlib.util.module_from_spec(_spec)
sys.modules["build_native_expressions"] = bne
_spec.loader.exec_module(bne)


def seg(video, text, handle="@a", start=1.0, end=5.0):
    return {"video_id": video, "start": start, "end": end, "text": text, "title": "T", "channel": handle, "handle": handle}


def fake_judgement(n, flag=True):
    return [
        {"id": i, "expression": f"x{i}", "non_compositional": flag, "kind": "idiom" if flag else "literal",
         "meaning_ko": "뜻", "why_hard_for_korean": "이유", "register": "casual", "example": "Example."}
        for i in range(1, n + 1)
    ]


class FixtureDbTest(unittest.TestCase):
    def test_only_source_genres_and_ok_videos_are_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "captions.db"
            conn = clipdb.connect(db)
            for handle, genre in (("@tv", "tv"), ("@teach", "daily"), ("@pod", "podcast")):
                clipdb.upsert_channel(conn, handle, handle, genre)
            now = "2026-01-01T00:00:00Z"
            for vid, handle, status in (("v1", "@tv", "ok"), ("v2", "@teach", "ok"), ("v3", "@pod", "ok"), ("v4", "@tv", "error")):
                clipdb.save_video(conn, {"id": vid, "channel_handle": handle, "title": vid}, status, "auto",
                                  [{"start": 1.0, "end": 4.0, "text": f"text of {vid}"}], now)
            conn.close()
            rows = list(bne.iter_segments(db))
        self.assertEqual({r["video_id"] for r in rows}, {"v1", "v3"})
        self.assertNotIn("daily", {r["genre"] for r in rows})


class CandidateTest(unittest.TestCase):
    def test_inflections_count_together(self):
        docs = [bne.lemmas("we ended up home"), bne.lemmas("they end up late"), bne.lemmas("it ends up fine")]
        counts = bne.count_ngrams(docs, [], min_count=1)
        self.assertEqual(counts[2][("end", "up")], 3)

    def test_apriori_skips_rare_prefix_but_keeps_seed(self):
        docs = [bne.lemmas("alpha beta gamma delta")] * 1 + [bne.lemmas("alpha zeta gamma")] * 3
        plain = bne.count_ngrams(docs, [], min_count=2)
        self.assertNotIn(("alpha", "beta", "gamma"), plain[3])
        seeded = bne.count_ngrams(docs, [("alpha", "beta", "gamma")], min_count=2)
        self.assertEqual(seeded[3][("alpha", "beta", "gamma")], 1)

    def test_noise_rules(self):
        self.assertTrue(bne.is_noise(("you", "know", "what")) is False)
        self.assertTrue(bne.is_noise(("of", "the")))
        self.assertTrue(bne.is_noise(("i", "think", "that")))
        self.assertTrue(bne.is_noise(("the", "big", "deal")))
        self.assertTrue(bne.is_noise(("very", "very")))
        self.assertFalse(bne.is_noise(("figure", "out")))
        self.assertFalse(bne.is_noise(("no", "big", "deal")))

    def test_min_split_pmi_value(self):
        counts = {1: Counter({"a": 20, "b": 25}), 2: Counter({("a", "b"): 10})}
        self.assertAlmostEqual(bne.min_split_pmi(("a", "b"), 10, counts, 1000), 4.3219, places=3)

    def test_score_filters_by_association_and_keeps_seeds(self):
        counts = {
            1: Counter({"red": 20, "balloon": 20, "very": 500, "good": 500}),
            2: Counter({("red", "balloon"): 18, ("very", "good"): 10, ("good", "balloon"): 3}),
        }
        found = {c["key"]: c for c in bne.score_candidates(counts, 100000, [("good", "balloon")], min_count=5, min_pmi=3.0)}
        self.assertIn("red balloon", found)
        self.assertNotIn("very good", found)
        self.assertIn("good balloon", found)
        self.assertTrue(found["good balloon"]["seed"])
        self.assertAlmostEqual(found["red balloon"]["per_million"], 18 / 100000 * 1e6)

    def test_build_candidates_end_to_end(self):
        texts = [
            "we need to figure out the plan",
            "can you figure out the answer",
            "I figured out the problem",
            "she is figuring out the code",
            "they figure out the rest soon",
            "let us figure out a way",
        ]
        segments = [seg(f"v{i}", t, handle="@a" if i % 2 else "@b") for i, t in enumerate(texts)]
        found, stats = bne.build_candidates(segments, limit=50, min_count=3, min_videos=2, min_channels=2)
        keys = {c["key"]: c for c in found}
        self.assertIn("figure out", keys)
        self.assertEqual(keys["figure out"]["count"], 6)
        self.assertEqual(keys["figure out"]["expression"], "figure out")
        self.assertEqual(stats["segments"], 6)
        self.assertNotIn("figure out the", keys)

    def test_display_form_prefers_base_when_common_enough(self):
        self.assertEqual(bne.display_form(Counter({"ended up": 10, "end up": 4}), "end up"), "end up")
        self.assertEqual(bne.display_form(Counter({"ended up": 10, "end up": 1}), "end up"), "ended up")


class ParseTest(unittest.TestCase):
    def test_clean_array(self):
        out = bne.parse_judgement(json.dumps(fake_judgement(3)))
        self.assertEqual([i["id"] for i in out], [1, 2, 3])
        self.assertTrue(out[0]["non_compositional"])
        self.assertEqual(out[0]["why_hard"], "이유")

    def test_fences_prose_and_trailing_comma(self):
        text = "Here you go:\n```json\n" + '[{"id": 1, "non_compositional": true, "kind": "idiom", "meaning_ko": "a", "why_hard_for_korean": "b",},]' + "\n```\nDone."
        out = bne.parse_judgement(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["kind"], "idiom")

    def test_truncated_tail_keeps_complete_items(self):
        full = json.dumps(fake_judgement(3))
        cut = full[: full.rfind("{")] + '{"id": 3, "non_comp'
        out = bne.parse_judgement(cut)
        self.assertEqual([i["id"] for i in out], [1, 2])

    def test_string_booleans_and_bad_items(self):
        text = json.dumps([
            {"id": "1", "non_compositional": "true", "kind": "Phrasal Verb", "register": "Slang"},
            {"id": 2, "non_compositional": "maybe"},
            {"non_compositional": True},
            "junk",
            {"id": 4, "non_compositional": False, "kind": "nonsense"},
        ])
        out = bne.parse_judgement(text)
        by_id = {i["id"]: i for i in out}
        self.assertEqual(set(by_id), {1, 4})
        self.assertEqual(by_id[1]["kind"], "phrasal_verb")
        self.assertEqual(by_id[1]["register"], "neutral")
        self.assertEqual(by_id[4]["kind"], "literal")

    def test_garbage_gives_empty(self):
        self.assertEqual(bne.parse_judgement("sorry, I cannot do that"), [])
        self.assertEqual(bne.parse_judgement(""), [])

    def test_duplicate_ids_keep_first(self):
        text = json.dumps([
            {"id": 1, "non_compositional": True, "kind": "idiom", "meaning_ko": "첫째"},
            {"id": 1, "non_compositional": False},
        ])
        out = bne.parse_judgement(text)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["meaning_ko"], "첫째")


class JudgeTest(unittest.TestCase):
    def batch(self, n):
        return [{"expression": f"e{i}", "example": "ex"} for i in range(n)]

    def test_prompt_numbers_each_item(self):
        prompt = bne.prompt_for(self.batch(3))
        for i in (1, 2, 3):
            self.assertIn(f'{i}. "e{i - 1}"', prompt)

    def test_missing_items_are_asked_again(self):
        calls = []

        def runner(prompt, model, work_dir, timeout):
            calls.append(prompt)
            if len(calls) == 1:
                return json.dumps(fake_judgement(3)[:2])
            return json.dumps(fake_judgement(1))

        judge = bne.Judge(Path("."), "m1", "m2", 5, runner=runner)
        result = judge.judge_batch(self.batch(3))
        self.assertEqual([r["id"] for r in result], [1, 2, 3])
        self.assertEqual(len(calls), 2)

    def test_quota_falls_back_then_stops(self):
        seen = []

        def runner(prompt, model, work_dir, timeout):
            seen.append(model)
            if model == "m1":
                raise bne.QuotaError("quota")
            return json.dumps(fake_judgement(2))

        judge = bne.Judge(Path("."), "m1", "m2", 5, runner=runner)
        self.assertEqual(len(judge.judge_batch(self.batch(2))), 2)
        self.assertEqual(seen, ["m1", "m2"])
        self.assertEqual(judge.current, "m2")

        def always(prompt, model, work_dir, timeout):
            raise bne.QuotaError("quota")

        stuck = bne.Judge(Path("."), "m1", "m2", 5, runner=always)
        with self.assertRaises(bne.StopPipeline):
            stuck.judge_batch(self.batch(2))


class FinalizeTest(unittest.TestCase):
    def test_keep_rule(self):
        base = {"non_compositional": True, "kind": "idiom", "meaning_ko": "뜻", "why_hard": "이유"}
        self.assertTrue(bne.keep_judged({}, base))
        self.assertFalse(bne.keep_judged({}, {**base, "non_compositional": False}))
        self.assertFalse(bne.keep_judged({}, {**base, "kind": "literal"}))
        self.assertFalse(bne.keep_judged({}, {**base, "meaning_ko": ""}))
        self.assertFalse(bne.keep_judged({}, {**base, "why_hard": ""}))

    def test_drop_contained_keeps_longer_when_nearly_as_common(self):
        items = [
            {"key": "come up", "count": 100, "per_million": 1},
            {"key": "come up with", "count": 80, "per_million": 1},
            {"key": "end up", "count": 100, "per_million": 1},
            {"key": "end up with", "count": 20, "per_million": 1},
        ]
        kept = {i["key"] for i in bne.drop_contained(items)}
        self.assertEqual(kept, {"come up with", "end up", "end up with"})

    def test_rank_orders_by_frequency_and_caps(self):
        items = [{"key": k, "per_million": p} for k, p in (("a", 1.0), ("b", 9.0), ("c", 5.0))]
        self.assertEqual([i["key"] for i in bne.rank(items, 2)], ["b", "c"])

    def test_pick_clips_distinct_videos_and_limit(self):
        pool = [
            {"video_id": "v1", "start": 0, "end": 4, "text": "one two three four five six seven", "title": "", "channel": "A"},
            {"video_id": "v1", "start": 9, "end": 13, "text": "one two three four five six seven", "title": "", "channel": "A"},
            {"video_id": "v2", "start": 0, "end": 4, "text": "one two three four five six seven", "title": "", "channel": "B"},
            {"video_id": "v3", "start": 0, "end": 4, "text": "one two three four five six seven", "title": "", "channel": "C"},
            {"video_id": "v4", "start": 0, "end": 4, "text": "one two three four five six seven", "title": "", "channel": "D"},
        ]
        chosen = bne.pick_clips(pool, random.Random(1))
        self.assertEqual(len(chosen), 3)
        self.assertEqual(len({c["video_id"] for c in chosen}), 3)

    def test_pick_clips_prefers_good_length(self):
        short = {"video_id": "s", "start": 0, "end": 1, "text": "oh", "title": "", "channel": "A"}
        good = {"video_id": "g", "start": 0, "end": 4, "text": "one two three four five six seven", "title": "", "channel": "B"}
        self.assertEqual(bne.pick_clips([short, good], random.Random(1), count=1)[0]["video_id"], "g")

    def test_collect_clips_matches_inflections_and_caps_pool(self):
        segments = [seg(f"v{i}", "we ended up there today") for i in range(bne.CLIP_POOL + 10)]
        segments.append(seg("other", "nothing relevant here"))
        pools = bne.collect_clips(segments, ["end up"], random.Random(1))
        self.assertEqual(len(pools["end up"]), bne.CLIP_POOL)
        self.assertNotIn("other", {c["video_id"] for c in pools["end up"]})

    def test_counts_by_kind_includes_all_kinds(self):
        tally = bne.counts_by_kind([{"kind": "idiom"}, {"kind": "idiom"}, {"kind": "chunk"}])
        self.assertEqual(tally, {"idiom": 2, "phrasal_verb": 0, "chunk": 1, "discourse_marker": 0})

    def test_learning_dir_is_refused(self):
        with self.assertRaises(SystemExit):
            bne.refuse_learning_dir(bne.LEARNING_DIR / "clipdb" / "native_expressions.json")
        bne.refuse_learning_dir(Path(tempfile.gettempdir()) / "x.json")

    def test_seed_list_is_normalized(self):
        keys = bne.seed_keys()
        self.assertIn(("figure", "out"), keys)
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(all(2 <= len(k) <= bne.MAX_N for k in keys))
        self.assertGreater(len(keys), 300)


if __name__ == "__main__":
    unittest.main()

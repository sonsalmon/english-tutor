import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import accent_key, pron

KST = accent_key.KST
MADE = datetime(2026, 10, 20, 9, 0, 0, tzinfo=KST)

ANSWERS = [
    {"id": "b1", "text": "We took the boat."},
    {"id": "b2", "text": "We took the boat."},
    {"id": "c2", "text": "I can go to the meeting tomorrow."},
    {"id": "c4", "text": "She can drive on the highway."},
    {"id": "c5", "text": "We can't finish it by Friday."},
    {"id": "c7", "text": "You can park here."},
    {"id": "t1", "text": "I have three tickets."},
    {"id": "t2", "text": "I have free tickets."},
    {"id": "p1", "text": "I bought a new pan."},
]


def make_result(answers=ANSWERS, made=MADE):
    return {"date": made.strftime("%Y-%m-%d"), "created_at": made.isoformat(timespec="seconds"), "contrasts": pron.judge_answers(answers)}


class TempPronDir(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "pron"
        patcher = mock.patch.dict(os.environ, {pron.PRON_DIR_ENV: str(self.dir)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def stored_file(self):
        return json.loads((self.dir / accent_key.KEY_FILE).read_text(encoding="utf-8"))


class HabitsTest(unittest.TestCase):
    def test_direction_counts_become_habits_with_strength_and_action(self):
        habits = {h["id"]: h for h in accent_key.habits_from_result(make_result())}

        vote = habits["b_v:vote"]
        self.assertEqual((vote["meant"], vote["heard_as"], vote["count"], vote["total"]), ("vote", "boat", 1, 1))
        self.assertEqual((vote["strength"], vote["action"]), ("strong", "practice"))
        self.assertEqual(vote["examples"], [{"meant_text": "We took the vote.", "heard_text": "We took the boat."}])
        self.assertIn("vote", vote["tip"])
        cant = habits["can_cant:can't"]
        self.assertEqual((cant["count"], cant["total"]), (3, 4))
        self.assertNotIn("p_f:pan", habits)
        self.assertNotIn("th_f:three", habits)
        self.assertNotIn("th_f:free", habits)
        self.assertEqual(
            [(e["meant_text"], e["heard_text"]) for e in cant["examples"]],
            [("I can't go to the meeting tomorrow.", "I can go to the meeting tomorrow."), ("She can't drive on the highway.", "She can drive on the highway.")],
        )

    def test_few_misses_among_many_sentences_are_only_adjusted(self):
        self.assertEqual(accent_key._strength(1, 5), "slight")
        self.assertEqual(accent_key._action("slight"), "adjust")
        self.assertEqual(accent_key._strength(1, 4), "mild")
        self.assertEqual(accent_key._strength(2, 4), "strong")

    def test_habits_are_sorted_strongest_first(self):
        habits = accent_key.habits_from_result(make_result())
        ratios = [h["count"] / h["total"] for h in habits]
        self.assertEqual(ratios, sorted(ratios, reverse=True))

    def test_old_result_without_directions_still_gives_habits(self):
        result = make_result()
        for c in result["contrasts"]:
            c.pop("directions")
        ids = {h["id"] for h in accent_key.habits_from_result(result)}
        self.assertIn("b_v:vote", ids)

    def test_no_result_no_habits(self):
        self.assertEqual(accent_key.habits_from_result(None), [])


class StoreTest(TempPronDir):
    def test_get_key_reads_without_writing_and_refresh_writes_once(self):
        result = make_result()

        key = accent_key.get_key(result)
        self.assertFalse((self.dir / accent_key.KEY_FILE).exists())
        self.assertIn("b_v:vote", {h["id"] for h in key["habits"]})

        accent_key.refresh(result)
        first = self.stored_file()
        self.assertEqual(first["source_date"], "2026-10-20")
        self.assertEqual({h["id"] for h in first["habits"]}, {h["id"] for h in key["habits"]})
        mtime = (self.dir / accent_key.KEY_FILE).stat().st_mtime_ns
        accent_key.refresh(result)
        self.assertEqual((self.dir / accent_key.KEY_FILE).stat().st_mtime_ns, mtime)

    def test_result_files_ignore_the_key_file(self):
        accent_key.refresh(make_result())
        self.assertIsNone(pron.latest_result())

    def test_broken_file_is_treated_as_empty(self):
        self.dir.mkdir(parents=True)
        (self.dir / accent_key.KEY_FILE).write_text("{not json", encoding="utf-8")
        self.assertEqual(accent_key.load_stored(), {"words": [], "removed": []})

    def test_finish_keeps_the_key_file_in_step_with_the_new_result(self):
        pron.finish([{"id": "b2", "text": "We took the boat."}], now=MADE)
        self.assertIn("b_v:vote", {h["id"] for h in self.stored_file()["habits"]})


class RemoveTest(TempPronDir):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(pron, "latest_result", return_value=make_result())
        self.latest = patcher.start()
        self.addCleanup(patcher.stop)

    def test_removed_habit_stays_gone_until_a_newer_test_shows_it_again(self):
        accent_key.refresh()
        key = accent_key.remove("habit", "b_v:vote", now=MADE + timedelta(days=1))
        self.assertNotIn("b_v:vote", {h["id"] for h in key["habits"]})
        self.assertNotIn("b_v:vote", {h["id"] for h in accent_key.refresh()["habits"]})

        self.latest.return_value = make_result(made=MADE + timedelta(days=2))
        self.assertIn("b_v:vote", {h["id"] for h in accent_key.refresh()["habits"]})

    def test_remove_unknown_or_bad_input(self):
        with self.assertRaises(KeyError):
            accent_key.remove("habit", "nope:nothing")
        with self.assertRaises(KeyError):
            accent_key.remove("word", "a>b")
        for kind, entry in (("other", "x"), ("habit", ""), ("habit", None), (None, "x")):
            with self.subTest(kind=kind, entry=entry), self.assertRaises(ValueError):
                accent_key.remove(kind, entry)

    def test_removed_word_is_deleted_and_not_merged_back_from_older_calls(self):
        pair = {"heard": "boat", "intended": "vote", "habit": "b_v:vote"}
        accent_key.merge_call_words("2026-10-21-100000", [pair])
        key = accent_key.remove("word", "boat>vote", now=datetime(2026, 10, 22, 8, 0, 0, tzinfo=KST))
        self.assertEqual(key["words"], [])

        self.assertEqual(accent_key.merge_call_words("2026-10-21-110000", [pair]), 0)
        self.assertEqual(accent_key.get_key()["words"], [])
        self.assertEqual(accent_key.merge_call_words("2026-10-23-090000", [pair]), 1)
        self.assertEqual([w["id"] for w in accent_key.get_key()["words"]], ["boat>vote"])


class MergeTest(TempPronDir):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(pron, "latest_result", return_value=make_result())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_counts_per_call_and_ignores_a_repeated_analysis_of_the_same_call(self):
        pair = {"heard": "boat", "intended": "vote", "habit": "b_v:vote"}

        self.assertEqual(accent_key.merge_call_words("2026-10-21-100000", [pair]), 1)
        self.assertEqual(accent_key.merge_call_words("2026-10-21-100000", [pair]), 0)
        self.assertEqual(accent_key.merge_call_words("2026-10-22-100000", [pair, {"heard": "free", "intended": "three", "habit": "th_f:three"}]), 2)

        words = {w["id"]: w for w in self.stored_file()["words"]}
        self.assertEqual(words["boat>vote"]["count"], 2)
        self.assertEqual(words["boat>vote"]["calls"], ["2026-10-21-100000", "2026-10-22-100000"])
        self.assertEqual(words["boat>vote"]["action"], "practice")
        self.assertEqual(words["free>three"]["count"], 1)

    def test_nothing_to_merge_writes_nothing(self):
        self.assertEqual(accent_key.merge_call_words("2026-10-21-100000", []), 0)
        self.assertEqual(accent_key.merge_call_words("2026-10-21-100000", None), 0)
        self.assertFalse((self.dir / accent_key.KEY_FILE).exists())

    def test_word_whose_habit_is_unknown_is_only_adjusted(self):
        accent_key.merge_call_words("2026-10-21-100000", [{"heard": "rice", "intended": "lice", "habit": ""}])
        self.assertEqual(self.stored_file()["words"][0]["action"], "adjust")


class AnalysisTest(unittest.TestCase):
    KEY = {"habits": accent_key.habits_from_result(make_result())}

    def test_section_lists_habit_ids_and_is_empty_without_habits(self):
        section = accent_key.analysis_section(self.KEY)
        self.assertIn("[b_v:vote]", section)
        self.assertIn("accent_misheard", section)
        self.assertEqual(accent_key.analysis_section({"habits": []}), "")
        self.assertEqual(accent_key.analysis_section(None), "")

    def test_normalize_keeps_only_words_the_learner_said_with_a_known_habit(self):
        raw = [
            {"heard": "boat", "intended": "vote", "habit": "b_v:vote"},
            {"heard": "boat", "intended": "vote", "habit": "b_v:vote"},
            {"heard": "ghost", "intended": "most", "habit": "b_v:vote"},
            {"heard": "free", "intended": "three", "habit": "nope:three"},
            {"heard": "Boat", "intended": "boat", "habit": "b_v:vote"},
            {"heard": "bad word", "intended": "x", "habit": "b_v:vote"},
            "junk",
        ]
        out = accent_key.normalize_misheard(raw, {"boat", "free", "i"}, self.KEY)
        self.assertEqual(out, [{"heard": "boat", "intended": "vote", "habit": "b_v:vote"}])
        self.assertEqual(accent_key.normalize_misheard(raw, {"boat"}, {"habits": []}), [])
        self.assertEqual(accent_key.normalize_misheard("junk", {"boat"}, self.KEY), [])

    def test_drop_explained_removes_only_pure_accent_corrections(self):
        pairs = [{"heard": "boat", "intended": "vote", "habit": "b_v:vote"}]
        rows = [
            {"said": "I want to boat for him", "better": "I want to vote for him", "why": "x"},
            {"said": "I want to boat for he", "better": "I want to vote for him", "why": "x"},
            {"said": "I goed home", "better": "I went home", "why": "x"},
        ]
        kept = accent_key.drop_explained(rows, pairs)
        self.assertEqual([r["said"] for r in kept], ["I want to boat for he", "I goed home"])
        self.assertIs(accent_key.drop_explained(rows, []), rows)


class BriefTest(unittest.TestCase):
    def test_words_brief_is_one_capped_line(self):
        key = {"words": [{"heard": "boat", "intended": "vote"}, {"heard": "free", "intended": "three"}]}
        self.assertEqual(
            accent_key.words_brief(key),
            "Words the learner meant that were heard as other words in earlier calls because of the accent (meant -> heard): vote -> boat; three -> free.",
        )
        self.assertEqual(accent_key.words_brief({"words": []}), "")
        many = {"words": [{"heard": f"h{i}ab", "intended": f"w{i}cd"} for i in range(60)]}
        self.assertLessEqual(len(accent_key.words_brief(many)), accent_key.BRIEF_WORDS_MAX_CHARS + 1)

    def test_without_removed_drops_the_removed_habit_from_the_result(self):
        result = make_result()
        key = {"habits": [h for h in accent_key.habits_from_result(result) if h["id"] != "b_v:vote"]}
        pruned = accent_key.without_removed(result, key)
        rows = {c["contrast"]: c for c in pruned["contrasts"]}
        self.assertEqual(rows["b_v"]["as_other"], 0)
        self.assertEqual(rows["b_v"]["misheard"], [])
        self.assertEqual(rows["can_cant"]["as_other"], 3)
        self.assertEqual({c["contrast"]: c["as_other"] for c in result["contrasts"]}["b_v"], 1)


class AccentKeyHttpTest(TempPronDir):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient

        from server import main

        self.client = TestClient(main.app)
        pron.finish(ANSWERS, now=MADE)

    def test_get_returns_habits_and_words_without_the_removed_log(self):
        accent_key.merge_call_words("2026-10-21-100000", [{"heard": "boat", "intended": "vote", "habit": "b_v:vote"}])

        body = self.client.get("/api/accent-key").json()

        self.assertEqual(body["source_date"], "2026-10-20")
        self.assertIn("b_v:vote", {h["id"] for h in body["habits"]})
        self.assertEqual([w["id"] for w in body["words"]], ["boat>vote"])
        self.assertNotIn("removed", body)

    def test_remove_a_habit_and_a_word_then_get_no_longer_lists_them(self):
        accent_key.merge_call_words("2026-10-21-100000", [{"heard": "boat", "intended": "vote", "habit": "b_v:vote"}])

        res = self.client.post("/api/accent-key/remove", json={"kind": "habit", "id": "b_v:vote"})
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("b_v:vote", {h["id"] for h in res.json()["habits"]})
        res = self.client.post("/api/accent-key/remove", json={"kind": "word", "id": "boat>vote"})
        self.assertEqual(res.json()["words"], [])
        again = self.client.get("/api/accent-key").json()
        self.assertNotIn("b_v:vote", {h["id"] for h in again["habits"]})
        self.assertEqual(again["words"], [])

    def test_remove_rejects_bad_requests(self):
        post = self.client.post
        self.assertEqual(post("/api/accent-key/remove", json={"kind": "habit", "id": "nope:x"}).status_code, 404)
        self.assertEqual(post("/api/accent-key/remove", json={"kind": "other", "id": "x"}).status_code, 400)
        self.assertEqual(post("/api/accent-key/remove", json={}).status_code, 400)
        self.assertEqual(post("/api/accent-key/remove", content="{}", headers={"content-type": "text/plain"}).status_code, 415)


if __name__ == "__main__":
    unittest.main()

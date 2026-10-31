import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from server import main, partner_memory as pm

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 20, 21, 0, 0, tzinfo=KST)
TURNS = [("me", "I'm going to a jazz concert on Saturday."), ("partner", "Nice!")]


def good(**extra):
    return {
        "fact_ops": [{"op": "ADD", "text": "Started learning the saxophone", "importance": 3}],
        "threads": [{"text": "The jazz concert on Saturday", "ko": "토요일 재즈 공연", "last_seen": "2026-10-20"}],
        **extra,
    }


class MemoryDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "pm"
        patcher = mock.patch.dict(os.environ, {"PARTNER_MEMORY_DIR": str(self.dir), "MEMORY_SETTINGS_PATH": str(Path(self._tmp.name) / "memory-settings.json")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def history(self):
        return sorted((self.dir / "history").glob("*.json")) if (self.dir / "history").exists() else []


class NormalizeTest(unittest.TestCase):
    def test_caps_lengths_and_dates(self):
        data = {
            "facts": [{"text": f"fact {i}", "last_seen": "2026-10-1%d" % (i % 10)} for i in range(15)]
            + [{"text": "x" * 200, "last_seen": "2026-10-20"}, {"text": "", "last_seen": "2026-10-20"}, "bad"],
            "threads": [{"text": f"thread {i}", "ko": "라벨", "last_seen": "garbage"} for i in range(8)]
            + [{"text": "no ko", "ko": "", "last_seen": "2026-10-20"}, {"text": "t", "ko": "가" * 31}],
        }

        out = pm.normalize(data, "priya", NOW)

        self.assertEqual(len(out["facts"]), 16)  # 사실은 개수 상한이 없고, 긴 글은 버리지 않고 자른다
        self.assertEqual(len(out["threads"]), 5)
        self.assertTrue(all(len(f["text"]) <= pm.FACT_MAX for f in out["facts"]))
        self.assertTrue(all(t["last_seen"] == "2026-10-20" for t in out["threads"]))
        self.assertEqual(set(out), {"partner", "version", "updated", "reflection", "facts", "threads", "self_story", "jokes", "episodes"})
        self.assertEqual(out["partner"], "priya")
        self.assertEqual(out["updated"], "2026-10-20T21:00:00+0900")

    def test_contact_details_are_dropped(self):
        data = {
            "facts": [
                {"text": "Email is a.b+c@example.com"},
                {"text": "Phone 010-1234-5678"},
                {"text": "Number +82 10 1234 5678"},
                {"text": "Blog at https://example.com/me"},
                {"text": "Site www.foo.org"},
                {"text": "Likes jazz since 2019"},
                {"text": "Has 3 cats and 12 plants"},
            ],
            "threads": [
                {"text": "Call 555 123 4567", "ko": "전화"},
                {"text": "Mail me", "ko": "x@y.com"},
                {"text": "The concert on Saturday", "ko": "토요일 공연"},
            ],
        }

        out = pm.normalize(data, "priya", NOW)

        self.assertEqual([f["text"] for f in out["facts"]], ["Likes jazz since 2019", "Has 3 cats and 12 plants"])
        self.assertEqual([t["text"] for t in out["threads"]], ["The concert on Saturday"])

    def test_memory_path_rejects_traversal(self):
        for bad in ("../x", "priya/../omar", "park", "", "priya/"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                pm.memory_path(bad)

    def test_duplicates_dropped_and_non_dict_rejected(self):
        out = pm.normalize({"facts": [{"text": "Likes jazz"}, {"text": "likes JAZZ"}]}, "omar", NOW)

        self.assertEqual(len(out["facts"]), 1)
        with self.assertRaises(ValueError):
            pm.normalize([], "omar", NOW)


class UpdateTest(MemoryDirCase):
    def test_writes_file_with_prompt_from_this_call_only(self):
        seen = []

        def gen(prompt):
            seen.append(prompt)
            return json.dumps(good())

        self.assertTrue(pm.update("priya", TURNS, gen, NOW))

        memory = json.loads((self.dir / "priya.json").read_text(encoding="utf-8"))
        self.assertEqual(memory["facts"][0]["text"], "Started learning the saxophone")
        self.assertEqual(memory["threads"][0]["ko"], "토요일 재즈 공연")
        self.assertIn("Priya", seen[0])
        self.assertIn("Me: I'm going to a jazz concert on Saturday.", seen[0])
        self.assertIn("Partner: Nice!", seen[0])
        self.assertEqual(self.history(), [])

    def test_second_update_backs_up_and_sends_old_memory(self):
        pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW)
        seen = []
        pm.update("priya", TURNS, lambda p: seen.append(p) or json.dumps(good(fact_ops=[{"op": "NOOP"}])), NOW + timedelta(days=1))

        self.assertIn("Started learning the saxophone", seen[0])
        backups = self.history()
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].name.startswith("priya-20261021-"))
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8"))["facts"][0]["text"], "Started learning the saxophone")
        self.assertEqual([f["text"] for f in pm.load_memory("priya")["facts"]], ["Started learning the saxophone"])  # 연산이 없으면 사실은 그대로

    def test_code_fenced_json_is_accepted(self):
        self.assertTrue(pm.update("jake", TURNS, lambda p: "```json\n" + json.dumps(good()) + "\n```", NOW))

    def test_every_failure_leaves_file_unchanged(self):
        pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW)
        before = (self.dir / "priya.json").read_text(encoding="utf-8")

        def boom(prompt):
            raise RuntimeError("vertex down")

        for gen in (boom, lambda p: "not json", lambda p: "[]", lambda p: ""):
            self.assertFalse(pm.update("priya", TURNS, gen, NOW))
        self.assertFalse(pm.update("park", TURNS, lambda p: json.dumps(good()), NOW))
        self.assertFalse(pm.update("priya", [("partner", "hi")], lambda p: json.dumps(good()), NOW))
        self.assertEqual((self.dir / "priya.json").read_text(encoding="utf-8"), before)
        self.assertFalse((self.dir / "park.json").exists())
        self.assertEqual(self.history(), [])

    def test_corrupt_old_file_is_backed_up_and_replaced(self):
        self.dir.mkdir(parents=True)
        (self.dir / "omar.json").write_text("{broken", encoding="utf-8")
        seen = []

        self.assertTrue(pm.update("omar", TURNS, lambda p: seen.append(p) or json.dumps(good()), NOW))

        self.assertEqual(pm.load_memory("omar")["facts"][0]["text"], "Started learning the saxophone")
        backups = self.history()
        self.assertEqual([b.read_text(encoding="utf-8") for b in backups], ["{broken"])
        self.assertIn("(none yet)", seen[0])

    def test_corrupt_file_stays_when_model_fails(self):
        self.dir.mkdir(parents=True)
        (self.dir / "omar.json").write_text("{broken", encoding="utf-8")

        self.assertFalse(pm.update("omar", TURNS, lambda p: "not json", NOW))
        self.assertEqual((self.dir / "omar.json").read_text(encoding="utf-8"), "{broken")

    def test_concurrent_updates_for_one_friend_do_not_overwrite_each_other(self):
        import threading

        inside = threading.Event()
        release = threading.Event()
        prompts = []

        def slow(prompt):
            prompts.append(prompt)
            inside.set()
            release.wait(5)
            return json.dumps(good())

        first = threading.Thread(target=pm.update, args=("priya", TURNS, slow, NOW))
        first.start()
        self.assertTrue(inside.wait(5))
        second = threading.Thread(target=pm.update, args=("priya", TURNS, lambda p: prompts.append(p) or json.dumps(good()), NOW))
        second.start()
        second.join(0.3)
        self.assertTrue(second.is_alive())  # 첫 갱신이 끝날 때까지 모델 호출도 못 한다
        self.assertEqual(len(prompts), 1)
        release.set()
        first.join(5)
        second.join(5)

        self.assertEqual(len(prompts), 2)
        self.assertIn("Started learning the saxophone", prompts[1])  # 두 번째는 첫 결과를 읽고 시작했다

    def test_no_temp_files_left(self):
        pm.update("chloe", TURNS, lambda p: json.dumps(good()), NOW)

        self.assertEqual([p.name for p in self.dir.glob("*.tmp")], [])


class ForgetTest(MemoryDirCase):
    def setUp(self):
        super().setUp()
        pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW)

    def test_clear_backs_up_then_deletes_and_is_idempotent(self):
        pm.clear_memory("priya", NOW)
        pm.clear_memory("priya", NOW)

        self.assertIsNone(pm.load_memory("priya"))
        self.assertEqual(len(self.history()), 1)

    def test_forget_item_backs_up_and_returns_memory(self):
        memory = pm.forget_item("priya", "threads", 0, NOW)

        self.assertEqual(memory["threads"], [])
        self.assertEqual(len(pm.load_memory("priya")["facts"]), 1)
        self.assertEqual(len(self.history()), 1)

    def test_out_of_range_and_bad_kind(self):
        for kind, index in (("facts", 1), ("facts", -1), ("threads", 5)):
            with self.assertRaises(IndexError):
                pm.forget_item("priya", kind, index, NOW)
        with self.assertRaises(ValueError):
            pm.forget_item("priya", "other", 0, NOW)
        self.assertEqual(self.history(), [])


class EndpointTest(MemoryDirCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(main.app)

    def test_get_empty_and_ok(self):
        res = self.client.get("/api/partners/priya/memory")
        self.assertEqual((res.status_code, res.json()), (200, {"status": "empty", "memory": None}))
        pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW)
        body = self.client.get("/api/partners/priya/memory").json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["memory"]["partner"], "priya")

    def test_unknown_ids_and_park_are_400(self):
        for pid in ("park", "nobody"):
            self.assertEqual(self.client.get(f"/api/partners/{pid}/memory").status_code, 400)
            self.assertEqual(self.client.delete(f"/api/partners/{pid}/memory").status_code, 400)
            self.assertEqual(self.client.delete(f"/api/partners/{pid}/memory/facts/0").status_code, 400)

    def test_delete_all(self):
        pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW)

        self.assertEqual(self.client.delete("/api/partners/priya/memory").json(), {"status": "ok"})
        self.assertEqual(self.client.get("/api/partners/priya/memory").json()["status"], "empty")

    def test_delete_item_cases(self):
        pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW)

        self.assertEqual(self.client.delete("/api/partners/priya/memory/facts/9").status_code, 404)
        self.assertEqual(self.client.delete("/api/partners/priya/memory/stuff/0").status_code, 400)
        res = self.client.delete("/api/partners/priya/memory/facts/0")
        self.assertEqual((res.status_code, res.json()["status"], res.json()["memory"]["facts"]), (200, "ok", []))
        self.assertEqual(self.client.delete("/api/partners/omar/memory/facts/0").status_code, 404)

    def test_delete_item_with_text_check(self):
        pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW)
        url = "/api/partners/priya/memory/facts/0"

        res = self.client.delete(url, params={"text": "Something else"})
        self.assertEqual((res.status_code, res.json()), (409, {"detail": "기억이 바뀌었어요. 다시 불러와 주세요."}))
        self.assertEqual(len(pm.load_memory("priya")["facts"]), 1)
        self.assertEqual(self.history(), [])

        res = self.client.delete(url, params={"text": "Started learning the saxophone"})
        self.assertEqual((res.status_code, res.json()["memory"]["facts"]), (200, []))

    def test_corrupt_file_is_500_not_empty(self):
        self.dir.mkdir(parents=True)
        (self.dir / "jake.json").write_text("{broken", encoding="utf-8")

        self.assertEqual(self.client.get("/api/partners/jake/memory").status_code, 500)


def v2(**extra):
    return {
        **good(),
        "self_story": [{"story": "Flatmate and the missing milk", "progress": "Her flatmate keeps drinking her milk; she left a note.", "last_seen": "2026-10-20"}],
        "jokes": [{"text": "Calling the flatmate the milk bandit", "last_seen": "2026-10-20"}],
        "episode": "Talked about the learner's jazz concert and the flatmate milk saga; cheerful.",
        **extra,
    }


class V2Test(MemoryDirCase):
    def test_v1_file_loads_with_empty_new_lists(self):
        self.dir.mkdir(parents=True)
        v1 = {"partner": "priya", "updated": "2026-10-01T00:00:00+0900", "facts": [{"text": "Likes tea", "last_seen": "2026-10-01"}], "threads": []}
        (self.dir / "priya.json").write_text(json.dumps(v1), encoding="utf-8")

        memory = pm.load_memory("priya")

        self.assertEqual(memory["facts"][0]["text"], "Likes tea")
        for key in ("self_story", "jokes", "episodes"):
            self.assertEqual(memory[key], [])

    def test_caps_and_length_limits(self):
        data = {
            "self_story": [{"story": f"s{i}", "progress": "p"} for i in range(10)]
            + [{"story": "x" * 61, "progress": "p"}, {"story": "ok", "progress": "y" * 161}, {"story": "np", "progress": ""}],
            "jokes": [{"text": f"j{i}"} for i in range(8)] + [{"text": "j" * 101}],
            "episodes": [{"date": f"2026-{i // 28 + 1:02d}-{i % 28 + 1:02d}", "mode": "call", "summary": f"e{i}"} for i in range(65)]
            + [{"date": "2026-10-20", "mode": "email", "summary": "bad mode"}, {"date": "2026-10-20", "mode": "chat", "summary": "z" * 201}],
        }

        out = pm.normalize(data, "priya", NOW)

        self.assertEqual((len(out["self_story"]), len(out["jokes"]), len(out["episodes"])), (8, 5, pm.MAX_EPISODES))
        self.assertEqual(out["episodes"][0]["date"], "2026-03-09")  # 최신순

    def test_update_call_adds_story_joke_and_episode(self):
        seen = []
        self.assertTrue(pm.update("priya", TURNS, lambda p: seen.append(p) or json.dumps(v2()), NOW))

        memory = pm.load_memory("priya")
        self.assertEqual(memory["self_story"][0]["story"], "Flatmate and the missing milk")
        self.assertEqual(memory["jokes"][0]["text"], "Calling the flatmate the milk bandit")
        self.assertEqual(memory["episodes"], [{"date": "2026-10-20", "mode": "call", "summary": v2()["episode"]}])
        self.assertIn("phone call", seen[0])
        self.assertIn("self_story", seen[0])

    def test_update_chat_adds_chat_episode_and_keeps_older_episodes(self):
        pm.update("priya", TURNS, lambda p: json.dumps(v2()), NOW)
        seen = []
        ok = pm.update("priya", TURNS, lambda p: seen.append(p) or json.dumps(v2(episode="Texted about weekend plans.")), NOW + timedelta(days=1), mode="chat")

        self.assertTrue(ok)
        self.assertIn("text chat", seen[0])
        episodes = pm.load_memory("priya")["episodes"]
        self.assertEqual([(e["date"], e["mode"]) for e in episodes], [("2026-10-21", "chat"), ("2026-10-20", "call")])

    def test_overlong_episode_is_trimmed_not_dropped(self):
        long = "word " * 60
        self.assertTrue(pm.update("priya", TURNS, lambda p: json.dumps(v2(episode=long)), NOW))

        summary = pm.load_memory("priya")["episodes"][0]["summary"]
        self.assertTrue(0 < len(summary) <= 200)

    def test_overlong_progress_is_cut_at_word_boundary_not_dropped(self):
        progress = " ".join(f"beat{i:02d}" for i in range(30))[:162]  # 162자
        out = pm.normalize({"self_story": [{"story": "Trek", "progress": progress}, {"story": "Tomato", "progress": "short"}]}, "priya", NOW)

        stories = {x["story"]: x["progress"] for x in out["self_story"]}
        self.assertEqual(set(stories), {"Trek", "Tomato"})
        self.assertTrue(0 < len(stories["Trek"]) <= pm.PROGRESS_MAX)
        self.assertTrue(progress.startswith(stories["Trek"]))
        self.assertFalse(stories["Trek"].endswith("beat"))  # 단어 한가운데에서 자르지 않는다

    def test_response_missing_list_keys_keeps_old_lists(self):
        old = v2()
        pm.update("priya", TURNS, lambda p: json.dumps(old), NOW)
        before = pm.load_memory("priya")
        self.assertTrue(before["self_story"] and before["jokes"])

        ok = pm.update("priya", TURNS, lambda p: json.dumps({"threads": [], "episode": "Short chat."}), NOW + timedelta(days=1))

        self.assertTrue(ok)
        after = pm.load_memory("priya")
        self.assertEqual(after["self_story"], before["self_story"])
        self.assertEqual(after["jokes"], before["jokes"])
        self.assertEqual(after["facts"], before["facts"])  # 연산 키가 없으면 사실도 그대로

    def test_long_episode_ends_at_sentence_boundary(self):
        long = "First we talked about the trek. " + "Then we kept chatting about many other things " * 8 + "The end."
        self.assertTrue(pm.update("priya", TURNS, lambda p: json.dumps(v2(episode=long)), NOW))

        summary = pm.load_memory("priya")["episodes"][0]["summary"]
        self.assertEqual(summary, "First we talked about the trek.")

    def test_long_episode_without_sentence_end_gets_ellipsis(self):
        long = "word " * 60
        self.assertTrue(pm.update("priya", TURNS, lambda p: json.dumps(v2(episode=long)), NOW))

        summary = pm.load_memory("priya")["episodes"][0]["summary"]
        self.assertTrue(summary.endswith("word…") and len(summary) <= pm.SUMMARY_MAX)

    def test_prompt_asks_for_bigger_storyline(self):
        self.assertIn("bigger storyline", pm.build_prompt("priya", None, TURNS, "2026-10-20"))

    def test_prompt_allows_remembering_the_learners_faith(self):
        prompt = pm.build_prompt("brian", None, TURNS, "2026-10-21")

        self.assertIn("- Faith:", prompt)
        self.assertNotIn("Faith privacy:", prompt)
        self.assertNotIn("never store the learner's own faith", prompt)
        self.assertIn("memory of Brian", prompt)

    def test_brian_memory_roundtrip(self):
        self.assertTrue(pm.valid_partner("brian"))
        self.assertTrue(pm.update("brian", TURNS, lambda p: json.dumps(v2()), NOW))
        self.assertEqual(pm.load_memory("brian")["partner"], "brian")

    def test_bad_mode_and_missing_episode(self):
        self.assertFalse(pm.update("priya", TURNS, lambda p: json.dumps(v2()), NOW, mode="email"))
        self.assertFalse((self.dir / "priya.json").exists())
        self.assertTrue(pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW, mode="chat"))
        self.assertEqual(pm.load_memory("priya")["episodes"], [])

    def test_forget_new_kinds_with_text_check(self):
        pm.update("priya", TURNS, lambda p: json.dumps(v2()), NOW)
        client = TestClient(main.app)
        base = "/api/partners/priya/memory"
        texts = {
            "self_story": "Her flatmate keeps drinking her milk; she left a note.",
            "jokes": "Calling the flatmate the milk bandit",
            "episodes": v2()["episode"],
        }

        for kind, text in texts.items():
            res = client.delete(f"{base}/{kind}/0", params={"text": "other"})
            self.assertEqual(res.status_code, 409, kind)
            self.assertEqual(len(pm.load_memory("priya")[kind]), 1)
            res = client.delete(f"{base}/{kind}/0", params={"text": text})
            self.assertEqual((res.status_code, res.json()["memory"][kind]), (200, []), kind)
        self.assertEqual(client.delete(f"{base}/jokes/0").status_code, 404)


V1_FILE = {
    "partner": "priya",
    "updated": "2026-10-21T10:00:00+0900",
    "facts": [
        {"text": "The learner likes tea.", "last_seen": "2026-10-21"},
        {"text": "The learner washed dishes at a cafeteria.", "last_seen": "2026-10-18"},
    ],
    "threads": [],
    "self_story": [],
    "jokes": [],
    "episodes": [],
}


def fact(id, text, **extra):
    return {"id": id, "text": text, "importance": 3, "first_seen": "2026-10-01", "last_seen": "2026-10-01", "status": "valid", "until": None, "source": None, **extra}


class MigrationTest(MemoryDirCase):
    def write_v1(self):
        self.dir.mkdir(parents=True)
        (self.dir / "priya.json").write_text(json.dumps(V1_FILE, indent=2), encoding="utf-8")

    def test_v1_facts_are_read_as_v2_without_touching_the_file(self):
        self.write_v1()
        before = (self.dir / "priya.json").read_bytes()

        memory = pm.load_memory("priya")

        self.assertEqual(memory["version"], 2)
        self.assertEqual([f["text"] for f in memory["facts"]], ["The learner likes tea.", "The learner washed dishes at a cafeteria."])
        for f in memory["facts"]:
            self.assertEqual((f["importance"], f["status"], f["until"], f["first_seen"] == f["last_seen"]), (3, "valid", None, True))
        self.assertEqual(sorted(f["id"] for f in memory["facts"]), ["f1", "f2"])
        self.assertIsNone(memory["reflection"])
        self.assertEqual((self.dir / "priya.json").read_bytes(), before)
        self.assertEqual(self.history(), [])

    def test_first_write_backs_up_the_v1_file_then_saves_v2_with_every_old_fact(self):
        self.write_v1()
        before = (self.dir / "priya.json").read_bytes()

        self.assertTrue(pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW))

        backups = self.history()
        self.assertEqual([b.read_bytes() for b in backups], [before])
        saved = json.loads((self.dir / "priya.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["version"], 2)
        texts = {f["text"] for f in saved["facts"]}
        self.assertEqual(texts, {"The learner likes tea.", "The learner washed dishes at a cafeteria.", "Started learning the saxophone"})
        self.assertEqual(len({f["id"] for f in saved["facts"]}), 3)

    def test_v2_roundtrip_keeps_ids_and_fields(self):
        self.write_v1()
        pm.update("priya", TURNS, lambda p: json.dumps(good()), NOW)
        first = pm.load_memory("priya")["facts"]

        pm.update("priya", TURNS, lambda p: json.dumps(good(fact_ops=[{"op": "NOOP"}])), NOW + timedelta(days=1))

        self.assertEqual(pm.load_memory("priya")["facts"], first)


class FactOpsTest(unittest.TestCase):
    def apply(self, facts, ops, today="2026-10-24", source="call-1"):
        return pm.apply_fact_ops(pm.normalize_facts(facts, today), ops, today, source)

    def test_add_creates_a_new_fact_with_dates_source_and_clamped_importance(self):
        facts, counts = self.apply([fact("f1", "Likes tea")], [{"op": "ADD", "text": "Runs a Go club at church", "importance": 9}])

        new = next(f for f in facts if f["id"] == "f2")
        self.assertEqual((new["importance"], new["first_seen"], new["last_seen"], new["status"], new["until"], new["source"]), (5, "2026-10-24", "2026-10-24", "valid", None, "call-1"))
        self.assertEqual(counts["ADD"], 1)
        self.assertEqual(len(facts), 2)

    def test_add_of_an_existing_valid_text_only_touches_it(self):
        facts, _ = self.apply([fact("f1", "Likes tea", importance=2)], [{"op": "ADD", "text": "likes TEA", "importance": 4}])

        self.assertEqual(len(facts), 1)
        self.assertEqual((facts[0]["last_seen"], facts[0]["importance"], facts[0]["first_seen"]), ("2026-10-24", 4, "2026-10-01"))

    def test_update_refines_text_importance_and_date(self):
        facts, _ = self.apply([fact("f1", "Likes tea")], [{"op": "UPDATE", "id": "f1", "text": "Likes green tea", "importance": 4}])
        self.assertEqual((facts[0]["text"], facts[0]["importance"], facts[0]["last_seen"]), ("Likes green tea", 4, "2026-10-24"))

        facts, _ = self.apply([fact("f1", "Likes tea")], [{"op": "UPDATE", "id": "f1"}])
        self.assertEqual((facts[0]["text"], facts[0]["importance"], facts[0]["last_seen"]), ("Likes tea", 3, "2026-10-24"))

    def test_past_keeps_the_fact_with_an_end_date_and_ids_are_not_reused(self):
        facts, counts = self.apply(
            [fact("f1", "Works at a cafeteria")],
            [{"op": "PAST", "id": "f1", "until": "2026-10-20"}, {"op": "ADD", "text": "Works at a library", "importance": 3}],
        )

        by_id = {f["id"]: f for f in facts}
        self.assertEqual((by_id["f1"]["status"], by_id["f1"]["until"], by_id["f1"]["text"]), ("past", "2026-10-20", "Works at a cafeteria"))
        self.assertEqual(by_id["f2"]["status"], "valid")
        self.assertEqual([f["id"] for f in facts], ["f2", "f1"])  # 지금 맞는 사실이 먼저, 지난 사실이 뒤
        self.assertEqual(counts["PAST"], 1)

    def test_update_on_a_past_fact_makes_it_valid_again(self):
        facts, _ = self.apply([fact("f1", "Plays piano", status="past", until="2026-09-01")], [{"op": "UPDATE", "id": "f1"}])

        self.assertEqual((facts[0]["status"], facts[0]["until"]), ("valid", None))

    def test_bad_operations_are_ignored(self):
        start = [fact("f1", "Likes tea")]
        ops = [
            {"op": "UPDATE", "id": "f99", "text": "x"},
            {"op": "PAST", "id": "nope"},
            {"op": "ADD", "text": "Mail me at a@b.com"},
            {"op": "ADD", "text": ""},
            {"op": "UPDATE", "id": "f1", "text": "Call 010-1234-5678"},
            {"op": "DELETE", "id": "f1"},
            "junk",
            {"op": "NOOP"},
        ]

        facts, counts = self.apply(start, ops)

        self.assertEqual([(f["id"], f["text"], f["last_seen"]) for f in facts], [("f1", "Likes tea", "2026-10-01")])
        self.assertEqual((counts["ignored"], counts["NOOP"]), (7, 1))

    def test_past_until_never_precedes_first_seen_and_ops_are_capped(self):
        facts, _ = self.apply([fact("f1", "A", first_seen="2026-10-10", last_seen="2026-10-10")], [{"op": "PAST", "id": "f1", "until": "2026-01-01"}])
        self.assertEqual(facts[0]["until"], "2026-10-10")

        many = [{"op": "ADD", "text": f"fact number {i}"} for i in range(pm.MAX_OPS + 30)]
        facts, _ = self.apply([], many)
        self.assertEqual(len(facts), pm.MAX_OPS)


class UpdateV2Test(MemoryDirCase):
    def test_facts_are_never_capped_or_silently_dropped_over_many_updates(self):
        for i in range(40):
            ops = [{"op": "ADD", "text": f"Learner fact number {i}", "importance": 1 + i % 5}]
            self.assertTrue(pm.update("priya", TURNS, lambda p, ops=ops: json.dumps({"fact_ops": ops, "episode": f"call {i}"}), NOW + timedelta(days=i)))

        memory = pm.load_memory("priya")

        self.assertEqual(len(memory["facts"]), 40)
        self.assertEqual(len(memory["episodes"]), 40)

    def test_contradicted_fact_becomes_past_and_new_one_is_added(self):
        pm.update("priya", TURNS, lambda p: json.dumps({"fact_ops": [{"op": "ADD", "text": "Works at a cafeteria", "importance": 3}], "episode": "a"}), NOW)
        ops = [{"op": "PAST", "id": "f1", "until": "2026-10-21"}, {"op": "ADD", "text": "Now works at a library", "importance": 3}]
        seen = []

        pm.update("priya", TURNS, lambda p: seen.append(p) or json.dumps({"fact_ops": ops, "episode": "b"}), NOW + timedelta(days=2), source="2026-10-22-100000")

        self.assertIn("f1 | importance 3 | valid", seen[0])
        facts = pm.load_memory("priya")["facts"]
        self.assertEqual([(f["id"], f["status"], f["until"], f["source"]) for f in facts], [("f2", "valid", None, "2026-10-22-100000"), ("f1", "past", "2026-10-21", "call-2026-10-20")])

    def test_prompt_lists_ids_importance_and_past_facts(self):
        old = {"facts": pm.normalize_facts([fact("f1", "Likes tea", importance=4), fact("f2", "Played piano", status="past", until="2026-09-01")], "2026-10-24")}

        prompt = pm.build_prompt("priya", old, TURNS, "2026-10-24")

        self.assertIn("f1 | importance 4 | valid | last_seen 2026-10-01 | Likes tea", prompt)
        self.assertIn("f2 | past since 2026-09-01 | Played piano", prompt)
        self.assertIn("fact_ops", prompt)
        self.assertNotIn('"reflection"', prompt)


class ReflectionTest(MemoryDirCase):
    PARAGRAPH = "The learner runs a Go club at church and likes jazz. They are warm and talk in short sentences."

    def response(self, **extra):
        return json.dumps({"fact_ops": [{"op": "NOOP"}], "episode": "chat", **extra})

    def test_written_once_per_day_per_friend(self):
        seen = []

        def gen(**extra):
            return lambda p: seen.append(p) or self.response(**extra)

        pm.update("priya", TURNS, gen(reflection=self.PARAGRAPH), NOW)
        pm.update("priya", TURNS, gen(reflection="Should be ignored today."), NOW + timedelta(hours=1))
        pm.update("jake", TURNS, gen(reflection="Jake's own paragraph."), NOW + timedelta(hours=1))
        pm.update("priya", TURNS, gen(reflection="A fresh paragraph on the next day."), NOW + timedelta(days=1))

        self.assertIn('"reflection"', seen[0])
        self.assertNotIn('"reflection"', seen[1])
        self.assertIn('"reflection"', seen[2])
        self.assertIn('"reflection"', seen[3])
        self.assertEqual(pm.load_memory("jake")["reflection"], {"text": "Jake's own paragraph.", "date": "2026-10-20"})
        self.assertEqual(pm.load_memory("priya")["reflection"], {"text": "A fresh paragraph on the next day.", "date": "2026-10-21"})

    def test_same_day_second_update_keeps_the_paragraph(self):
        pm.update("priya", TURNS, lambda p: self.response(reflection=self.PARAGRAPH), NOW)
        pm.update("priya", TURNS, lambda p: self.response(reflection="ignored"), NOW + timedelta(hours=2))

        self.assertEqual(pm.load_memory("priya")["reflection"]["text"], self.PARAGRAPH)

    def test_long_paragraph_is_trimmed_and_missing_paragraph_is_retried(self):
        long = "The learner likes jazz. " * 60
        pm.update("priya", TURNS, lambda p: self.response(reflection=long), NOW)
        self.assertLessEqual(len(pm.load_memory("priya")["reflection"]["text"]), pm.REFLECTION_MAX)

        seen = []
        pm.update("omar", TURNS, lambda p: seen.append(p) or self.response(), NOW)
        pm.update("omar", TURNS, lambda p: seen.append(p) or self.response(), NOW + timedelta(minutes=5))

        self.assertIsNone(pm.load_memory("omar")["reflection"])
        self.assertIn('"reflection"', seen[1])  # 문단을 못 받으면 다음 갱신에 다시 묻는다

    def test_forgetting_an_item_clears_the_paragraph(self):
        pm.update("priya", TURNS, lambda p: json.dumps(good(reflection=self.PARAGRAPH)), NOW)
        self.assertIsNotNone(pm.load_memory("priya")["reflection"])

        pm.forget_item("priya", "facts", 0, NOW)

        self.assertIsNone(pm.load_memory("priya")["reflection"])


if __name__ == "__main__":
    unittest.main()

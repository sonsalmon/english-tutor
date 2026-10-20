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
        "facts": [{"text": "Started learning the saxophone", "last_seen": "2026-10-20"}],
        "threads": [{"text": "The jazz concert on Saturday", "ko": "토요일 재즈 공연", "last_seen": "2026-10-20"}],
        **extra,
    }


class MemoryDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name) / "pm"
        patcher = mock.patch.dict(os.environ, {"PARTNER_MEMORY_DIR": str(self.dir)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def history(self):
        return sorted((self.dir / "history").glob("*.json")) if (self.dir / "history").exists() else []


class NormalizeTest(unittest.TestCase):
    def test_caps_lengths_and_dates(self):
        data = {
            "facts": [{"text": f"fact {i}", "last_seen": "2026-10-1%d" % (i % 10)} for i in range(15)]
            + [{"text": "x" * 121, "last_seen": "2026-10-20"}, {"text": "", "last_seen": "2026-10-20"}, "bad"],
            "threads": [{"text": f"thread {i}", "ko": "라벨", "last_seen": "garbage"} for i in range(8)]
            + [{"text": "no ko", "ko": "", "last_seen": "2026-10-20"}, {"text": "t", "ko": "가" * 31}],
        }

        out = pm.normalize(data, "priya", NOW)

        self.assertEqual(len(out["facts"]), 12)
        self.assertEqual(len(out["threads"]), 5)
        self.assertTrue(all(len(f["text"]) <= 120 for f in out["facts"]))
        self.assertTrue(all(t["last_seen"] == "2026-10-20" for t in out["threads"]))
        self.assertEqual(set(out), {"partner", "updated", "facts", "threads"})
        self.assertEqual(out["partner"], "priya")
        self.assertEqual(out["updated"], "2026-10-20T21:00:00+0900")

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
        pm.update("priya", TURNS, lambda p: seen.append(p) or json.dumps(good(facts=[])), NOW + timedelta(days=1))

        self.assertIn("Started learning the saxophone", seen[0])
        backups = self.history()
        self.assertEqual(len(backups), 1)
        self.assertTrue(backups[0].name.startswith("priya-20261021-"))
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8"))["facts"][0]["text"], "Started learning the saxophone")
        self.assertEqual(pm.load_memory("priya")["facts"], [])

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

    def test_corrupt_old_file_is_not_overwritten(self):
        self.dir.mkdir(parents=True)
        (self.dir / "omar.json").write_text("{broken", encoding="utf-8")

        self.assertFalse(pm.update("omar", TURNS, lambda p: json.dumps(good()), NOW))
        self.assertEqual((self.dir / "omar.json").read_text(encoding="utf-8"), "{broken")

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

    def test_corrupt_file_is_500_not_empty(self):
        self.dir.mkdir(parents=True)
        (self.dir / "jake.json").write_text("{broken", encoding="utf-8")

        self.assertEqual(self.client.get("/api/partners/jake/memory").status_code, 500)


if __name__ == "__main__":
    unittest.main()

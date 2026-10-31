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

from server import main, memory_settings as ms, partner_memory as pm

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 20, 21, 0, 0, tzinfo=KST)
TURNS = [("me", "I'm going to a jazz concert on Saturday."), ("partner", "Nice!")]
ALL_ON = {"facts": True, "threads": True, "interests": True}


def settings(about_me="", **remember):
    return {"about_me": about_me, "remember": {**ALL_ON, **remember}}


def model(**extra):
    return {
        "fact_ops": [{"op": "ADD", "text": "Started learning the saxophone", "importance": 3}],
        "threads": [{"text": "The jazz concert on Saturday", "ko": "토요일 재즈 공연", "last_seen": "2026-10-20"}],
        "episode": "Talked about a jazz concert.",
        "reflection": "The learner likes jazz.",
        **extra,
    }


class SettingsPathCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "sub" / "memory-settings.json"
        patcher = mock.patch.dict(
            os.environ,
            {"MEMORY_SETTINGS_PATH": str(self.path), "PARTNER_MEMORY_DIR": str(Path(self._tmp.name) / "pm")},
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)


class StoreTest(SettingsPathCase):
    def test_missing_file_gives_defaults(self):
        self.assertEqual(
            ms.load_settings(),
            {"version": 1, "about_me": "", "remember": ALL_ON, "updated": ""},
        )

    def test_round_trip_strips_text_and_ignores_unknown_keys(self):
        saved = ms.save_settings({**settings("  I run a Go club at church.  ", interests=False), "extra": 1, "remember_x": 2}, NOW)

        self.assertEqual(saved["about_me"], "I run a Go club at church.")
        self.assertEqual(saved["remember"], {"facts": True, "threads": True, "interests": False})
        self.assertEqual(saved["updated"], "2026-10-20T21:00:00+09:00")
        self.assertEqual(ms.load_settings(), saved)
        self.assertEqual(set(json.loads(self.path.read_text(encoding="utf-8"))), {"version", "about_me", "remember", "updated"})
        self.assertEqual([p.name for p in self.path.parent.glob("*.tmp")], [])

    def test_text_at_the_limit_is_ok_and_over_it_is_not(self):
        self.assertEqual(len(ms.save_settings(settings("가" * ms.ABOUT_ME_MAX), NOW)["about_me"]), ms.ABOUT_ME_MAX)
        with self.assertRaises(ValueError):
            ms.save_settings(settings("가" * (ms.ABOUT_ME_MAX + 1)), NOW)

    def test_invalid_payloads_raise_and_leave_file_alone(self):
        ms.save_settings(settings("keep"), NOW)
        before = self.path.read_text(encoding="utf-8")
        bad = [
            "text",
            {"remember": ALL_ON},
            {"about_me": 5, "remember": ALL_ON},
            {"about_me": "x"},
            {"about_me": "x", "remember": "on"},
            {"about_me": "x", "remember": {"facts": True, "threads": True}},
            {"about_me": "x", "remember": {**ALL_ON, "threads": "yes"}},
            {"about_me": "x", "remember": {**ALL_ON, "facts": 1}},
        ]
        for payload in bad:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    ms.save_settings(payload, NOW)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_corrupt_or_wrong_shape_file_gives_defaults(self):
        self.path.parent.mkdir(parents=True)
        for text in ("{broken", "[]", json.dumps({"about_me": 1, "remember": ALL_ON}), json.dumps({"about_me": "x", "remember": {"facts": "no"}})):
            with self.subTest(text=text):
                self.path.write_text(text, encoding="utf-8")
                with self.assertLogs(ms.logger, level="ERROR"):
                    self.assertEqual(ms.load_settings(), ms.default_settings())


class EndpointTest(SettingsPathCase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(main.app)

    def test_get_defaults_then_put_round_trip(self):
        self.assertEqual(self.client.get("/api/memory-settings").json(), ms.default_settings())

        res = self.client.put("/api/memory-settings", json=settings("I like jazz.", facts=False))

        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual((body["about_me"], body["remember"]), ("I like jazz.", {"facts": False, "threads": True, "interests": True}))
        self.assertEqual(self.client.get("/api/memory-settings").json(), body)

    def test_invalid_values_are_400(self):
        for payload in (settings("가" * 1501), settings(7), {"about_me": "x", "remember": {**ALL_ON, "facts": "off"}}, ["x"]):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.put("/api/memory-settings", json=payload).status_code, 400)
        self.assertFalse(self.path.exists())

    def test_non_json_content_type_is_415(self):
        res = self.client.put("/api/memory-settings", content=json.dumps(settings("x")), headers={"content-type": "text/plain"})

        self.assertEqual(res.status_code, 415)
        self.assertFalse(self.path.exists())


class PartnerMemoryGatingTest(SettingsPathCase):
    def update(self, output, now=NOW, prompts=None):
        def generate(prompt):
            if prompts is not None:
                prompts.append(prompt)
            return json.dumps(output)

        return pm.update("priya", TURNS, generate, now)

    def test_all_on_stores_facts_threads_episode_and_reflection(self):
        self.assertTrue(self.update(model()))

        memory = pm.load_memory("priya")
        self.assertEqual([f["text"] for f in memory["facts"]], ["Started learning the saxophone"])
        self.assertEqual(len(memory["threads"]), 1)
        self.assertEqual(len(memory["episodes"]), 1)
        self.assertEqual(memory["reflection"]["text"], "The learner likes jazz.")

    def test_facts_off_skips_fact_ops_reflection_and_episodes_but_keeps_stored_data(self):
        self.update(model())
        ms.save_settings(settings(facts=False), NOW)
        prompts = []

        ok = self.update(
            model(
                fact_ops=[{"op": "ADD", "text": "Has a dog named Rex", "importance": 5}],
                episode="Talked about the dog.",
                reflection="A new paragraph.",
                self_story=[{"story": "My trek", "progress": "Booked the flight.", "last_seen": "2026-10-21"}],
                jokes=[{"text": "The sax thing", "last_seen": "2026-10-21"}],
            ),
            NOW + timedelta(days=1),
            prompts,
        )

        self.assertTrue(ok)
        memory = pm.load_memory("priya")
        self.assertEqual([f["text"] for f in memory["facts"]], ["Started learning the saxophone"])
        self.assertEqual([e["summary"] for e in memory["episodes"]], ["Talked about a jazz concert."])
        self.assertEqual(memory["reflection"]["text"], "The learner likes jazz.")
        self.assertEqual([s["story"] for s in memory["self_story"]], ["My trek"])  # 친구 이야기와 농담은 영향을 받지 않는다
        self.assertEqual([j["text"] for j in memory["jokes"]], ["The sax thing"])
        self.assertNotIn("reflection", prompts[0].split("Return ONLY")[1])  # 문단을 쓰라고 요구하지도 않는다

    def test_threads_off_keeps_stored_threads_unchanged_and_facts_still_work(self):
        self.update(model())
        before = pm.load_memory("priya")["threads"]
        ms.save_settings(settings(threads=False), NOW)

        new_thread = [{"text": "The dog's vet visit", "ko": "강아지 병원", "last_seen": "2026-10-21"}]
        self.update(model(fact_ops=[{"op": "ADD", "text": "Has a dog", "importance": 3}], threads=new_thread), NOW + timedelta(days=1))

        memory = pm.load_memory("priya")
        self.assertEqual(memory["threads"], before)
        self.assertEqual(len(memory["facts"]), 2)
        self.assertEqual(len(memory["episodes"]), 2)

    def test_settings_are_read_on_every_update(self):
        ms.save_settings(settings(facts=False), NOW)
        self.update(model())
        self.assertEqual(pm.load_memory("priya")["facts"], [])

        ms.save_settings(settings(), NOW)
        self.update(model(), NOW + timedelta(days=1))

        self.assertEqual(len(pm.load_memory("priya")["facts"]), 1)


if __name__ == "__main__":
    unittest.main()

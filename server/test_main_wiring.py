import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import main

TRANSCRIPT = Path("/nonexistent/2026-10-20-090000.md")
TUTORING = {"corrections": [{"said": "I just start", "better": "I just started", "why": "x"}]}


class FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class TutorEndpointWiringTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        main._TUTOR_CACHE.clear()
        main._PROFILE_UPDATED.clear()
        patches = {
            "resolve": mock.patch.object(main, "_wait_and_resolve_transcript", return_value=TRANSCRIPT),
            "run": mock.patch.object(main, "run_tutoring", side_effect=lambda path: (dict(TUTORING), True)),
            "schedule": mock.patch.object(main, "_schedule_profile_update"),
        }
        self.mocks = {name: p.start() for name, p in patches.items()}
        for p in patches.values():
            self.addCleanup(p.stop)

    async def test_fresh_tutoring_schedules_one_card_update(self):
        await main.tutor_endpoint(FakeRequest({}))

        self.mocks["schedule"].assert_called_once_with(TUTORING)

    async def test_cached_result_does_not_update_card(self):
        await main.tutor_endpoint(FakeRequest({}))
        await main.tutor_endpoint(FakeRequest({}))

        self.assertEqual(self.mocks["run"].call_count, 1)
        self.mocks["schedule"].assert_called_once()

    async def test_same_call_analyzed_again_after_cache_expiry_updates_card_once(self):
        await main.tutor_endpoint(FakeRequest({}))
        main._TUTOR_CACHE.clear()
        await main.tutor_endpoint(FakeRequest({}))

        self.assertEqual(self.mocks["run"].call_count, 2)
        self.mocks["schedule"].assert_called_once()

    async def test_teachback_does_not_update_card(self):
        with mock.patch.object(main, "get_lesson", return_value={"date": "2026-10-13", "sections": []}), \
                mock.patch.object(main, "lesson_text", return_value=""), \
                mock.patch.object(main, "run_teachback", return_value=({"unanswered": []}, True)):
            await main.tutor_endpoint(FakeRequest({"mode": "teachback"}))

        self.mocks["schedule"].assert_not_called()


class LearnerProfileEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_broken_card_gives_empty_brief(self):
        with mock.patch.object(main, "load_profile", side_effect=main.ProfileError("broken")):
            self.assertEqual(await main.learner_profile_endpoint(), {"brief": "", "updated": None})

    async def test_missing_card_gives_empty_brief(self):
        with mock.patch.object(main, "load_profile", return_value=None):
            self.assertEqual(await main.learner_profile_endpoint(), {"brief": "", "updated": None})


if __name__ == "__main__":
    unittest.main()

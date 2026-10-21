import asyncio
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import call_bot, history, main, summary_jobs
from server.call_bot import CallConfig, CallRecord, parse_call_config

STEM = "2026-10-20-090000"
INSTRUCTION = 'You are Ms. Park.\nThe user ... trying to: "Day 1 Team Intro" (intro)'
TUTORING = {"corrections": [{"said": "I just start", "better": "I just started", "why": "x"}]}
TRANSCRIPT_TEXT = (
    "# Call 2026-10-20 09:00\n- mission: Ordering coffee\n- model: test-model\n"
    "- duration: 2m 30s\n- completed: yes\n- coach: 0\n\n**Me:** Hello there my friend\n"
)


class FakeRequest:
    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


class SummaryJobsRegistryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        summary_jobs.reset()

    async def test_concurrent_waits_share_one_job(self):
        calls = []
        started, release = asyncio.Event(), asyncio.Event()

        async def factory():
            calls.append(1)
            started.set()
            await release.wait()
            return {"ok": True}

        first = asyncio.create_task(summary_jobs.wait("s", factory))
        await started.wait()
        second = asyncio.create_task(summary_jobs.wait("s", factory))
        self.assertEqual(summary_jobs.job_status("s"), summary_jobs.RUNNING)
        release.set()

        self.assertEqual(await asyncio.gather(first, second), [{"ok": True}, {"ok": True}])
        self.assertEqual(len(calls), 1)
        self.assertEqual(summary_jobs.job_status("s"), summary_jobs.DONE)
        self.assertEqual(await summary_jobs.wait("s", factory), {"ok": True})
        self.assertEqual(len(calls), 1)

    async def test_cancelled_requester_does_not_stop_the_job(self):
        started, release = asyncio.Event(), asyncio.Event()

        async def factory():
            started.set()
            await release.wait()
            return {"ok": True}

        requester = asyncio.create_task(summary_jobs.wait("s", factory))
        await started.wait()
        requester.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await requester
        job = summary_jobs._JOBS["s"]
        self.assertEqual(job.status, summary_jobs.RUNNING)
        release.set()
        await job.task

        self.assertEqual((job.status, job.result), (summary_jobs.DONE, {"ok": True}))

    async def test_failed_job_raises_for_joiners_and_next_start_retries(self):
        attempts = []

        async def factory():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("boom")
            return {"ok": True}

        with self.assertRaises(RuntimeError):
            await summary_jobs.wait("s", factory)
        self.assertEqual(summary_jobs.job_status("s"), summary_jobs.FAILED)
        self.assertEqual(summary_jobs.unfinished_status("s"), summary_jobs.FAILED)

        self.assertEqual(await summary_jobs.wait("s", factory), {"ok": True})
        self.assertEqual(len(attempts), 2)

    async def test_failure_nobody_received_goes_to_the_first_joiner_then_retries(self):
        attempts = []

        async def factory():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("boom")
            return {"ok": True}

        job = summary_jobs.start("s", factory)
        await job.task

        with self.assertRaises(RuntimeError):
            await summary_jobs.wait("s", factory)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(await summary_jobs.wait("s", factory), {"ok": True})
        self.assertEqual(len(attempts), 2)

    async def test_unknown_stem_is_pending(self):
        self.assertEqual(summary_jobs.job_status("none"), summary_jobs.PENDING)
        self.assertEqual(summary_jobs.unfinished_status("none"), summary_jobs.PENDING)


class CallConfigInputsTest(unittest.TestCase):
    def test_lesson_date_and_practice_words_are_recorded_at_call_start(self):
        config = parse_call_config(
            {
                "system_instruction": INSTRUCTION,
                "mode": "teachback",
                "lesson_date": "2026-10-13",
                "practice_words": ["swamped", "Bad Word", 5, "circle-back"],
            }
        )

        self.assertEqual(config.lesson_date, "2026-10-13")
        self.assertEqual(config.practice_words, ("swamped", "circle-back"))

    def test_inputs_are_optional(self):
        config = parse_call_config({"system_instruction": INSTRUCTION, "mode": "mission"})

        self.assertEqual((config.lesson_date, config.practice_words), (None, ()))

    def test_bad_lesson_date_is_rejected(self):
        for date in ("2026-13-45", "yesterday", 20261013):
            with self.subTest(date=date), self.assertRaises(ValueError):
                parse_call_config({"system_instruction": INSTRUCTION, "mode": "teachback", "lesson_date": date})

    def test_job_spec_survives_a_json_round_trip_and_ignores_garbage(self):
        spec = summary_jobs.JobSpec("teachback", "2026-10-13", ("swamped",))
        self.assertEqual(summary_jobs.JobSpec.from_json(spec.to_json()), spec)
        self.assertEqual(
            summary_jobs.JobSpec.from_json({"mode": 3, "lesson_date": "nope", "practice_words": "x"}),
            summary_jobs.JobSpec(),
        )


class NotifyCallSavedTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(call_bot.configure_call_saved, None)
        self.hook = mock.Mock()
        call_bot.configure_call_saved(self.hook)
        self.config = CallConfig(system_instruction=INSTRUCTION, mode="mission")

    def record(self, text):
        record = CallRecord()
        record.add_user(text)
        return record

    def test_hook_runs_when_the_learner_spoke(self):
        self.assertTrue(call_bot.notify_call_saved(Path("/x/a.md"), self.config, self.record("hello there my friend")))
        self.hook.assert_called_once_with(Path("/x/a.md"), self.config)

    def test_no_hook_when_the_learner_barely_spoke_or_nothing_was_saved(self):
        self.assertFalse(call_bot.notify_call_saved(Path("/x/a.md"), self.config, self.record("hi")))
        self.assertFalse(call_bot.notify_call_saved(None, self.config, self.record("hello there my friend")))
        self.hook.assert_not_called()

    def test_hook_error_never_breaks_the_call_ending(self):
        self.hook.side_effect = RuntimeError("boom")
        self.assertFalse(call_bot.notify_call_saved(Path("/x/a.md"), self.config, self.record("hello there my friend")))


class CallEndSummaryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        summary_jobs.reset()
        main._PROFILE_UPDATED.clear()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.sessions, self.tutoring, self.teachback = root / "sessions", root / "tutoring", root / "teachback"
        for directory in (self.sessions, self.tutoring, self.teachback):
            directory.mkdir()
        patcher = mock.patch.dict(
            os.environ,
            {
                "TRANSCRIPT_DIR": str(self.sessions),
                "TUTORING_DIR": str(self.tutoring),
                "TEACHBACK_DIR": str(self.teachback),
                "AUDIO_DIR": str(root / "audio"),
                "KNOWN_EXPRESSIONS_PATH": str(root / "known.json"),
            },
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.path = self.sessions / f"{STEM}.md"
        self.path.write_text(TRANSCRIPT_TEXT, encoding="utf-8")

        self.gate = threading.Event()
        self.gate.set()
        self.outcomes = []
        self.run = mock.patch.object(main, "run_tutoring", side_effect=self.fake_run).start()
        self.defer = mock.patch.object(main.review, "defer_card_update").start()
        self.addCleanup(mock.patch.stopall)

    def fake_run(self, path):
        self.assertTrue(self.gate.wait(5), "gate never opened")
        outcome = self.outcomes.pop(0) if self.outcomes else None
        if outcome is not None:
            raise outcome
        (self.tutoring / f"{Path(path).stem}.json").write_text(json.dumps(TUTORING), encoding="utf-8")
        return dict(TUTORING), True

    def config(self, mode="mission", **extra):
        return CallConfig(system_instruction=INSTRUCTION, mode=mode, **extra)

    def listed(self):
        [call] = history.list_calls()
        return call["summary"]

    async def finish_job(self):
        await summary_jobs._JOBS[STEM].task

    async def test_call_end_starts_one_background_job_and_status_walks_to_done(self):
        self.assertEqual(self.listed(), "pending")
        self.gate.clear()

        main._on_call_saved(self.path, self.config())

        self.assertEqual(self.listed(), "running")
        self.assertEqual(history.load_call(STEM)["call"]["summary"], "running")
        self.gate.set()
        await self.finish_job()
        self.assertEqual(self.listed(), "done")
        self.assertEqual(self.run.call_count, 1)

    async def test_tutor_endpoint_joins_the_running_job_and_the_finished_one(self):
        self.gate.clear()
        main._on_call_saved(self.path, self.config())

        request = asyncio.create_task(main.tutor_endpoint(FakeRequest({"filename": f"{STEM}.md", "practice_words": ["hello"]})))
        self.gate.set()
        body = json.loads((await request).body)
        again = json.loads((await main.tutor_endpoint(FakeRequest({"filename": f"{STEM}.md"}))).body)

        self.assertEqual(self.run.call_count, 1)
        self.assertEqual((body["stem"], again["stem"]), (STEM, STEM))
        self.assertEqual(body["corrections"], TUTORING["corrections"])
        self.assertEqual(self.defer.call_count, 1)

    async def test_tutor_endpoint_without_a_server_job_starts_it_once(self):
        first = json.loads((await main.tutor_endpoint(FakeRequest({"filename": f"{STEM}.md"}))).body)
        second = json.loads((await main.tutor_endpoint(FakeRequest({"filename": f"{STEM}.md"}))).body)

        self.assertEqual(self.run.call_count, 1)
        self.assertEqual(first["stem"], second["stem"])

    async def test_server_recorded_practice_words_are_used_for_practice_used(self):
        main._on_call_saved(self.path, self.config(practice_words=("hello", "zebra")))
        await self.finish_job()

        body = json.loads((await main.tutor_endpoint(FakeRequest({"filename": f"{STEM}.md", "practice_words": ["zebra"]}))).body)

        self.assertEqual(body["practice_used"], ["hello"])

    async def test_failed_job_is_failed_for_the_page_and_retry_starts_a_new_one(self):
        self.outcomes = [main.TutoringAnalysisError("빈 결과")]
        main._on_call_saved(self.path, self.config())
        await self.finish_job()

        self.assertEqual(self.listed(), "failed")
        self.assertEqual(self.run.call_count, 1)

        self.gate.clear()
        self.assertEqual(await main.call_summary_endpoint(STEM), {"summary": "running"})
        self.assertEqual(self.listed(), "running")
        self.gate.set()
        await self.finish_job()

        self.assertEqual(self.listed(), "done")
        self.assertEqual(self.run.call_count, 2)

    async def test_page_joining_a_failed_job_gets_the_error_with_stem(self):
        self.outcomes = [main.TutoringAnalysisError("빈 결과")]
        main._on_call_saved(self.path, self.config())

        response = await main.tutor_endpoint(FakeRequest({"filename": f"{STEM}.md"}))

        self.assertEqual(response.status_code, 502)
        self.assertEqual(json.loads(response.body)["stem"], STEM)
        self.assertEqual(self.run.call_count, 1)
        self.assertEqual(self.listed(), "failed")

    async def test_retry_after_a_restart_for_a_call_with_transcript_and_no_summary(self):
        self.assertEqual(self.listed(), "pending")

        self.assertEqual(await main.call_summary_endpoint(STEM), {"summary": "running"})
        await self.finish_job()

        self.assertEqual(self.listed(), "done")
        self.assertEqual(await main.call_summary_endpoint(STEM), {"summary": "done"})
        self.assertEqual(self.run.call_count, 1)

    async def test_stored_summary_is_returned_without_calling_the_model(self):
        (self.tutoring / f"{STEM}.json").write_text(json.dumps(TUTORING), encoding="utf-8")

        body = json.loads((await main.tutor_endpoint(FakeRequest({"filename": f"{STEM}.md"}))).body)

        self.run.assert_not_called()
        self.assertEqual((body["stem"], body["saved"]), (STEM, True))
        self.defer.assert_not_called()

    async def test_retry_endpoint_validates_the_stem(self):
        with self.assertRaises(main.HTTPException) as bad:
            await main.call_summary_endpoint("../etc")
        with self.assertRaises(main.HTTPException) as missing:
            await main.call_summary_endpoint("2026-01-01-000000")

        self.assertEqual((bad.exception.status_code, missing.exception.status_code), (400, 404))

    async def test_teachback_inputs_are_recorded_and_survive_a_restart(self):
        lesson = {"date": "2026-10-13", "sections": []}
        result = {"corrections": [], "lesson_date": "2026-10-13"}
        with mock.patch.object(main, "get_lesson", return_value=lesson) as get_lesson, \
                mock.patch.object(main, "lesson_text", return_value="notes"), \
                mock.patch.object(main, "run_teachback", side_effect=lambda *a: (dict(result), True)) as run_teachback:
            main._on_call_saved(self.path, self.config("teachback", lesson_date="2026-10-13"))
            await self.finish_job()

            get_lesson.assert_called_once_with("2026-10-13")
            self.assertEqual(run_teachback.call_args.args[1:], ("notes", "2026-10-13"))
            self.run.assert_not_called()
            self.assertEqual(summary_jobs.read_spec(STEM), summary_jobs.JobSpec("teachback", "2026-10-13", ()))

            summary_jobs.reset()
            await main.call_summary_endpoint(STEM)
            await self.finish_job()

            self.assertEqual(get_lesson.call_count, 2)
            self.assertEqual(get_lesson.call_args.args, ("2026-10-13",))
            self.assertEqual(run_teachback.call_count, 2)
            self.run.assert_not_called()

    async def test_every_mode_gets_a_job(self):
        for mode in call_bot.MODES:
            with self.subTest(mode=mode):
                summary_jobs.reset()
                (self.tutoring / f"{STEM}.json").unlink(missing_ok=True)
                with mock.patch.object(main, "get_lesson", return_value={"date": "2026-10-13"}), \
                        mock.patch.object(main, "lesson_text", return_value=""), \
                        mock.patch.object(main, "run_teachback", return_value=({"corrections": []}, True)) as teachback:
                    main._on_call_saved(self.path, self.config(mode))
                    await self.finish_job()
                self.assertEqual(summary_jobs.job_status(STEM), summary_jobs.DONE)
                self.assertEqual(teachback.call_count, 1 if mode == "teachback" else 0)


if __name__ == "__main__":
    unittest.main()

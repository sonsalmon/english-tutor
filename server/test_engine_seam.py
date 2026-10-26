import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipecat.services.google.gemini_live.llm import GeminiLiveLLMService

from server import call_bot, engines
from server.engines import base

MISSING = "server.engines._not_there"


def request(**extra):
    return {"system_instruction": "You are a friend.", "mode": "smalltalk", **extra}


def fake_module(unavailable=None):
    module = types.ModuleType("server.engines.fake_engine")
    module.build_parts = mock.Mock(return_value=base.EngineParts(model_name="fake-model", llm=object()))
    if unavailable is not None:
        module.unavailable_reason = lambda: unavailable
    return module


class ParseEngineTest(unittest.TestCase):
    def test_absent_or_empty_engine_is_the_default(self):
        for extra in ({}, {"engine": ""}, {"engine": None}):
            with self.subTest(extra=extra):
                self.assertEqual(call_bot.parse_call_config(request(**extra)).engine, "gemini_live")
        self.assertEqual(call_bot.parse_call_config({"system_instruction": "x"}).engine, "gemini_live")

    def test_default_engine_works_in_every_mode(self):
        for mode in call_bot.MODES:
            self.assertEqual(call_bot.parse_call_config(request(mode=mode, engine="gemini_live")).engine, "gemini_live")

    def test_unknown_engine_is_rejected(self):
        for value in ("bogus", "Gemini_Live", 5, ["gemini_live"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                call_bot.parse_call_config(request(engine=value))

    def test_experimental_engines_need_smalltalk(self):
        for engine in ("gemini_live_notes", "openai_live", "cascade_flux"):
            for mode in ("mission", "freetalk", "teachback"):
                with self.subTest(engine=engine, mode=mode), self.assertRaises(ValueError) as caught:
                    call_bot.parse_call_config(request(mode=mode, engine=engine))
                self.assertIn("친구 수다", str(caught.exception))

    def test_gemini_notes_engine_needs_no_module(self):
        config = call_bot.parse_call_config(request(engine="gemini_live_notes"))

        self.assertEqual(config.engine, "gemini_live_notes")

    def test_engine_without_module_is_not_ready(self):
        with mock.patch.dict(base.ENGINE_MODULES, {"openai_live": MISSING}):
            with self.assertRaises(ValueError) as caught:
                call_bot.parse_call_config(request(engine="openai_live"))

        self.assertEqual(str(caught.exception), base.ENGINE_NOT_READY)

    def test_engine_module_decides_availability(self):
        with mock.patch.dict(sys.modules, {"server.engines.fake_engine": fake_module()}), mock.patch.dict(
            base.ENGINE_MODULES, {"openai_live": "server.engines.fake_engine"}
        ):
            self.assertEqual(call_bot.parse_call_config(request(engine="openai_live")).engine, "openai_live")
        with mock.patch.dict(sys.modules, {"server.engines.fake_engine": fake_module("OPENAI_API_KEY 없음")}), mock.patch.dict(
            base.ENGINE_MODULES, {"openai_live": "server.engines.fake_engine"}
        ):
            with self.assertRaises(ValueError) as caught:
                call_bot.parse_call_config(request(engine="openai_live"))
        self.assertEqual(str(caught.exception), "OPENAI_API_KEY 없음")

    def test_broken_engine_module_is_a_400_reason_not_a_crash(self):
        with mock.patch("server.engines.base.importlib.import_module", side_effect=RuntimeError("boom")):
            reason = base.engine_unavailable_reason("cascade_flux")

        self.assertIn("boom", reason)


class RunBotBranchTest(unittest.TestCase):
    def test_non_gemini_engine_goes_to_run_engine(self):
        config = call_bot.CallConfig(system_instruction="x", mode="smalltalk", engine="openai_live")
        with mock.patch.object(engines, "run_engine", mock.AsyncMock()) as run_engine:
            asyncio.run(call_bot.run_bot("connection", config))

        run_engine.assert_awaited_once_with("connection", config)

    def test_gemini_engines_do_not_touch_run_engine(self):
        for engine in call_bot.GEMINI_ENGINES:
            config = call_bot.CallConfig(system_instruction="x", mode="smalltalk", engine=engine)
            with mock.patch.object(engines, "run_engine", mock.AsyncMock()) as run_engine, mock.patch.object(
                call_bot, "live_config_for", side_effect=RuntimeError("default path")
            ):
                with self.assertRaises(RuntimeError):
                    asyncio.run(call_bot.run_bot("connection", config))
            run_engine.assert_not_awaited()

    def test_run_engine_hands_parts_to_the_shell(self):
        module = fake_module()
        config = call_bot.CallConfig(system_instruction="x", mode="smalltalk", engine="openai_live")
        from server.engines import shell

        with mock.patch.dict(sys.modules, {"server.engines.fake_engine": module}), mock.patch.dict(
            engines.ENGINES, {"openai_live": "server.engines.fake_engine"}
        ), mock.patch.object(shell, "run_engine_call", mock.AsyncMock()) as run_call:
            asyncio.run(engines.run_engine("connection", config))

        module.build_parts.assert_called_once_with(config)
        run_call.assert_awaited_once_with("connection", config, module.build_parts.return_value)

    def test_run_engine_disconnects_when_the_engine_cannot_start(self):
        module = fake_module()
        module.build_parts.side_effect = RuntimeError("no key")
        connection = mock.Mock(disconnect=mock.AsyncMock())
        config = call_bot.CallConfig(system_instruction="x", mode="smalltalk", engine="openai_live")

        with mock.patch.dict(sys.modules, {"server.engines.fake_engine": module}), mock.patch.dict(
            engines.ENGINES, {"openai_live": "server.engines.fake_engine"}
        ):
            asyncio.run(engines.run_engine(connection, config))

        connection.disconnect.assert_awaited_once()


def note_service(partner_speaking=False, responding=False):
    service = object.__new__(call_bot.live_service_class())
    service._partner_speaking, service._bot_is_responding = partner_speaking, responding
    service._disconnecting, service._session = False, mock.Mock(send_client_content=mock.AsyncMock())
    service._drop_rest_of_turn = False
    return service


class SendNoteTest(unittest.TestCase):
    def test_idle_partner_gets_the_note_without_a_reply_request(self):
        service = note_service()

        asyncio.run(service.send_note("  you disagree, one playful reason  "))

        service._session.send_client_content.assert_awaited_once_with(
            turns=[{"role": "user", "parts": [{"text": "you disagree, one playful reason"}]}], turn_complete=False)

    def test_empty_note_is_ignored(self):
        service = note_service()

        asyncio.run(service.send_note("   "))

        service._session.send_client_content.assert_not_awaited()

    def test_note_waits_until_the_partner_turn_is_complete(self):
        for kwargs in ({"partner_speaking": True}, {"responding": True}):
            with self.subTest(kwargs=kwargs):
                service = note_service(**kwargs)
                base_turn_complete = mock.AsyncMock()
                with mock.patch.object(GeminiLiveLLMService, "_handle_msg_turn_complete", base_turn_complete):
                    asyncio.run(service.send_note("continue your story"))
                    service._session.send_client_content.assert_not_awaited()
                    asyncio.run(service._handle_msg_turn_complete("done"))

                base_turn_complete.assert_awaited_once()
                service._session.send_client_content.assert_awaited_once()
                self.assertEqual(service.__dict__.get("_pending_notes", []), [])

    def test_note_is_dropped_when_there_is_no_session(self):
        service = note_service()
        service._session = None

        asyncio.run(service.send_note("hello"))


class FakeListener:
    instruction_suffix = "DIRECTOR'S NOTES"

    def __init__(self):
        self.sink, self.turns = None, []

    def attach(self, note_sink):
        self.sink = note_sink

    async def on_user_turn(self, text):
        self.turns.append(text)


class TurnListenerTest(unittest.TestCase):
    def tearDown(self):
        call_bot.configure_turn_listener(None)

    def test_no_factory_means_no_listener(self):
        self.assertIsNone(call_bot.make_turn_listener(call_bot.CallConfig("x", "smalltalk"), call_bot.CallRecord()))

    def test_factory_receives_config_and_record(self):
        listener = FakeListener()
        factory = mock.Mock(return_value=listener)
        config, record = call_bot.CallConfig("x", "smalltalk"), call_bot.CallRecord()
        call_bot.configure_turn_listener(factory)

        self.assertIs(call_bot.make_turn_listener(config, record), listener)
        factory.assert_called_once_with(config, record)
        self.assertIsInstance(listener, base.TurnListener)

    def test_broken_factory_does_not_stop_the_call(self):
        call_bot.configure_turn_listener(mock.Mock(side_effect=RuntimeError("boom")))

        self.assertIsNone(call_bot.make_turn_listener(call_bot.CallConfig("x", "smalltalk"), call_bot.CallRecord()))

    def test_failing_listener_is_swallowed(self):
        listener = mock.Mock(on_user_turn=mock.AsyncMock(side_effect=RuntimeError("boom")))

        asyncio.run(call_bot.notify_turn_listener(listener, "hi there friend"))

        listener.on_user_turn.assert_awaited_once_with("hi there friend")

    def test_live_service_is_a_note_sink(self):
        self.assertIsInstance(note_service(), base.NoteSink)


class ShellImportTest(unittest.TestCase):
    def test_shell_imports_and_unknown_model_cost_is_none(self):
        from server.engines import shell

        record = call_bot.CallRecord()
        record.usage.add_tokens(100, 50, None, None)

        self.assertTrue(callable(shell.run_engine_call))
        self.assertIsNone(call_bot.estimate_cost("gpt-live-1", record.usage))


if __name__ == "__main__":
    unittest.main()

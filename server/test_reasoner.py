import asyncio
import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import call_bot, reasoner

INSTRUCTION = """WHO YOU ARE
You are Jake Miller, 27, a junior software developer from Columbus, Ohio, USA.

VALUES & OPINIONS
Likes: smash burgers.
Mild opinions you defend: a thin smash burger beats a thick one every time.
When the learner disagrees, push back playfully with one reason.

WHAT YOU REMEMBER ABOUT THE LEARNER (notes from earlier calls):
<<<
Learner likes hiking. Works in logistics.
>>>
The example sentences are from EARLIER calls."""

LEARNER = "I think thick burgers are much better"


def words(n):
    return " ".join(f"w{i}" for i in range(n))


class FakeSink:
    def __init__(self):
        self.notes = []

    async def send_note(self, text):
        self.notes.append(text)


class FakeModel:
    """모델 호출을 흉내 낸다. gate를 주면 그 신호가 올 때까지 호출 스레드가 막힌다."""

    def __init__(self, replies, gate=None):
        self.replies = list(replies)
        self.gate = gate
        self.started = threading.Event()
        self.prompts = []
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def __call__(self, prompt):
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            index = len(self.prompts)
            self.prompts.append(prompt)
        self.started.set()
        try:
            if self.gate is not None and index == 0:
                self.gate.wait(5)
            reply = self.replies[min(index, len(self.replies) - 1)]
            if isinstance(reply, Exception):
                raise reply
            return reply
        finally:
            with self._lock:
                self.active -= 1


def note_json(note, hold=()):
    return json.dumps({"note": note, "hold_for_end": list(hold)})


def make(model, chunks=None, clock=None):
    record = SimpleNamespace(chunks=chunks if chunks is not None else [("Partner", "Hey!"), ("Me", LEARNER)])
    config = SimpleNamespace(system_instruction=INSTRUCTION, engine="gemini_live_notes")
    ticks = iter(range(0, 1000, 2))
    listener = reasoner.Reasoner(config, record, generate_text=model, clock=clock or (lambda: float(next(ticks))))
    sink = FakeSink()
    listener.attach(sink)
    return listener, sink, record


async def settle(listener):
    while listener._worker is not None and not listener._worker.done():
        await asyncio.shield(listener._worker)


class ClampNoteTest(unittest.TestCase):
    def test_short_note_is_kept(self):
        self.assertEqual(reasoner.clamp_note("Push back once. Bring in your 1-and-4 story."), "Push back once. Bring in your 1-and-4 story.")

    def test_exactly_forty_words_is_kept(self):
        note = words(40)
        self.assertEqual(reasoner.clamp_note(note), note)

    def test_long_note_is_cut_at_a_sentence_end(self):
        note = f"{words(30)}. {words(30)}."
        cut = reasoner.clamp_note(note)

        self.assertEqual(cut, f"{words(30)}.")
        self.assertLessEqual(reasoner.word_count(cut), reasoner.MAX_NOTE_WORDS)

    def test_long_note_without_a_sentence_end_is_dropped(self):
        self.assertIsNone(reasoner.clamp_note(words(60)))

    def test_empty_note_is_dropped(self):
        for note in ("", "   ", None):
            self.assertIsNone(reasoner.clamp_note(note))

    def test_newlines_collapse_to_one_line(self):
        self.assertEqual(reasoner.clamp_note("Disagree.\n\nGive one reason."), "Disagree. Give one reason.")


class ParseNoteTest(unittest.TestCase):
    def test_json(self):
        self.assertEqual(reasoner.parse_note(note_json("Push back.", ["fix later"])), ("Push back.", ["fix later"]))

    def test_fenced_json(self):
        self.assertEqual(reasoner.parse_note("```json\n" + note_json("Push back.") + "\n```"), ("Push back.", []))

    def test_plain_text_is_the_note(self):
        self.assertEqual(reasoner.parse_note("Answer first, then share your story."), ("Answer first, then share your story.", []))

    def test_non_string_is_empty(self):
        self.assertEqual(reasoner.parse_note(None), ("", []))
        self.assertEqual(reasoner.parse_note("[1, 2]"), ("", []))


class PromptTest(unittest.TestCase):
    def test_prompt_has_name_stance_memory_and_recent_turns_only(self):
        chunks = []
        for i in range(12):
            chunks.append(("Me", f"learner line {i}"))
            chunks.append(("Partner", f"partner line {i}"))
        chunks.insert(3, ("Me (shared)", "https://example.com/secret"))

        prompt = reasoner.build_prompt(INSTRUCTION, chunks)

        self.assertIn("their friend Jake.", prompt)
        self.assertIn("a thin smash burger beats a thick one", prompt)
        self.assertIn("When the learner disagrees", prompt)
        self.assertIn("Learner likes hiking", prompt)
        self.assertIn("partner line 11", prompt)
        self.assertNotIn("learner line 7", prompt)
        self.assertNotIn("secret", prompt)
        self.assertEqual(prompt.count("\nMe: "), 4)
        self.assertEqual(prompt.count("\nPartner: "), 4)

    def test_prompt_survives_an_instruction_without_stance_or_memory(self):
        prompt = reasoner.build_prompt("Be nice.", [("Me", "hello there friend")])

        self.assertIn("the friend", prompt)
        self.assertIn("Me: hello there friend", prompt)

    def test_stance_header_wins_over_values_and_opinions(self):
        text = "STANCE\nI hate cilantro.\n\nVALUES & OPINIONS\nLikes: tea."

        self.assertEqual(reasoner.persona_stance(text), "I hate cilantro.")


class ReasonerFlowTest(unittest.IsolatedAsyncioTestCase):
    async def test_note_is_sent_with_prefix_and_logged(self):
        listener, sink, _ = make(FakeModel([note_json("Disagree playfully, then tell your 1-and-4 story.")]))

        with self.assertLogs("server.reasoner", level="INFO") as logs:
            await listener.on_user_turn(LEARNER)
            await settle(listener)

        self.assertEqual(sink.notes, [reasoner.NOTE_PREFIX + "Disagree playfully, then tell your 1-and-4 story."])
        self.assertTrue(any("Note injected (2.0s after learner turn): " in line for line in logs.output), logs.output)

    async def test_note_over_forty_words_is_cut_or_dropped(self):
        long_note = f"{words(30)}. {words(30)}."
        listener, sink, _ = make(FakeModel([note_json(long_note), note_json(words(60))]))

        await listener.on_user_turn(LEARNER)
        await settle(listener)
        await listener.on_user_turn(LEARNER)
        await settle(listener)

        self.assertEqual(sink.notes, [reasoner.NOTE_PREFIX + f"{words(30)}."])
        for note in sink.notes:
            self.assertLessEqual(reasoner.word_count(note.removeprefix(reasoner.NOTE_PREFIX)), reasoner.MAX_NOTE_WORDS)

    async def test_empty_note_sends_nothing(self):
        listener, sink, _ = make(FakeModel([note_json("")]))

        await listener.on_user_turn(LEARNER)
        await settle(listener)

        self.assertEqual(sink.notes, [])

    async def test_short_turn_does_not_call_the_model(self):
        model = FakeModel([note_json("Never sent.")])
        listener, sink, _ = make(model)

        await listener.on_user_turn("Mm-hm, yeah")
        await settle(listener)

        self.assertEqual(model.prompts, [])
        self.assertEqual(sink.notes, [])

    async def test_stale_result_is_dropped_and_only_one_request_runs_at_a_time(self):
        gate = threading.Event()
        model = FakeModel([note_json("OLD note for turn one."), note_json("NEW note for turn two.")], gate=gate)
        listener, sink, record = make(model)

        await listener.on_user_turn(LEARNER)
        await asyncio.to_thread(model.started.wait, 5)
        record.chunks.append(("Me", "actually I changed my mind about burgers"))
        await listener.on_user_turn("actually I changed my mind about burgers")
        self.assertEqual(len(model.prompts), 1, "second turn must wait for the request in flight")
        gate.set()
        await settle(listener)

        self.assertEqual(sink.notes, [reasoner.NOTE_PREFIX + "NEW note for turn two."])
        self.assertEqual(len(model.prompts), 2)
        self.assertEqual(model.max_active, 1)
        self.assertIn("changed my mind", model.prompts[1])

    async def test_short_turn_after_a_request_makes_that_result_stale(self):
        gate = threading.Event()
        model = FakeModel([note_json("OLD note.")], gate=gate)
        listener, sink, _ = make(model)

        await listener.on_user_turn(LEARNER)
        await asyncio.to_thread(model.started.wait, 5)
        await listener.on_user_turn("yeah")
        gate.set()
        await settle(listener)

        self.assertEqual(sink.notes, [])
        self.assertEqual(len(model.prompts), 1)

    async def test_model_error_is_logged_and_the_next_turn_still_works(self):
        listener, sink, _ = make(FakeModel([RuntimeError("vertex down"), note_json("Answer first.")]))

        with self.assertLogs("server.reasoner", level="ERROR") as logs:
            await listener.on_user_turn(LEARNER)
            await settle(listener)
        self.assertTrue(any("vertex down" in line for line in logs.output))
        self.assertEqual(sink.notes, [])

        await listener.on_user_turn(LEARNER)
        await settle(listener)
        self.assertEqual(sink.notes, [reasoner.NOTE_PREFIX + "Answer first."])

    async def test_sink_error_does_not_raise(self):
        listener, sink, _ = make(FakeModel([note_json("Answer first.")]))

        async def broken(text):
            raise ConnectionError("session closed")

        sink.send_note = broken
        with self.assertLogs("server.reasoner", level="ERROR"):
            await listener.on_user_turn(LEARNER)
            await settle(listener)

    async def test_no_sink_means_no_model_call(self):
        model = FakeModel([note_json("Never sent.")])
        record = SimpleNamespace(chunks=[("Me", LEARNER)])
        listener = reasoner.Reasoner(SimpleNamespace(system_instruction=INSTRUCTION), record, generate_text=model)

        await listener.on_user_turn(LEARNER)
        await settle(listener)

        self.assertEqual(model.prompts, [])


class FactoryTest(unittest.TestCase):
    def config(self, engine=None, mode="smalltalk"):
        extra = {} if engine is None else {"engine": engine}
        return call_bot.parse_call_config({"system_instruction": INSTRUCTION, "mode": mode, **extra})

    def test_only_the_notes_engine_gets_a_listener(self):
        record = SimpleNamespace(chunks=[])

        self.assertIsInstance(reasoner.listener_factory(self.config("gemini_live_notes"), record), reasoner.Reasoner)
        for engine in (None, "gemini_live", "openai_live", "cascade_flux"):
            with self.subTest(engine=engine):
                self.assertIsNone(reasoner.listener_factory(self.config(engine) if engine in (None, "gemini_live") else SimpleNamespace(engine=engine), record))

    def test_suffix_is_the_director_paragraph_and_only_for_the_notes_listener(self):
        listener = reasoner.listener_factory(self.config("gemini_live_notes"), SimpleNamespace(chunks=[]))

        self.assertTrue(listener.instruction_suffix.startswith("DIRECTOR'S NOTES:"))
        self.assertIn("[Director's note", listener.instruction_suffix)
        self.assertIn("Do not reply to it; wait for the learner.", listener.instruction_suffix)

    def test_listener_satisfies_the_turn_listener_protocol(self):
        from server.engines.base import TurnListener

        listener = reasoner.listener_factory(self.config("gemini_live_notes"), SimpleNamespace(chunks=[]))

        self.assertIsInstance(listener, TurnListener)

    def test_call_bot_adds_the_suffix_only_when_the_factory_returns_a_listener(self):
        previous = call_bot._turn_listener_factory
        try:
            call_bot.configure_turn_listener(reasoner.listener_factory)
            record = SimpleNamespace(chunks=[])
            self.assertIsNotNone(call_bot.make_turn_listener(self.config("gemini_live_notes"), record))
            self.assertIsNone(call_bot.make_turn_listener(self.config(), record))
        finally:
            call_bot.configure_turn_listener(previous)

    def test_main_registers_the_factory(self):
        previous = call_bot._turn_listener_factory
        try:
            call_bot.configure_turn_listener(None)
            import importlib

            from server import main

            importlib.reload(main)
            self.assertIs(call_bot._turn_listener_factory, reasoner.listener_factory)
        finally:
            call_bot.configure_turn_listener(previous)


if __name__ == "__main__":
    unittest.main()

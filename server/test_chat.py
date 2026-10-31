import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import chat, partner_memory


class ChatTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = {"CHAT_DIR": str(Path(self.tmp.name) / "chats"), "PARTNER_MEMORY_DIR": str(Path(self.tmp.name) / "memory"), "MEMORY_SETTINGS_PATH": str(Path(self.tmp.name) / "memory-settings.json")}
        patcher = mock.patch.dict("os.environ", env)
        patcher.start()
        self.addCleanup(patcher.stop)
        chat._INFLIGHT.clear()
        chat._CLIENT = None

    def say(self, pid, n, start=0):
        chat.append_messages(
            pid,
            [{"role": "me" if (start + i) % 2 == 0 else "friend", "text": f"m{start + i}", "at": "2026-10-20T10:00:00+09:00"} for i in range(n)],
        )


class RequestCheckTest(ChatTestCase):
    def test_accepts_trimmed_message(self):
        self.assertEqual(chat.check_request("be Priya", "  hi  "), ("be Priya", "hi"))

    def test_rejects_bad_values(self):
        for instruction, message in [
            ("", "hi"),
            ("x", ""),
            ("x", "   "),
            ("x", 5),
            (None, "hi"),
            ("x" * (chat.MAX_INSTRUCTION + 1), "hi"),
            ("x", "y" * (chat.MAX_MESSAGE + 1)),
        ]:
            with self.subTest(instruction=str(instruction)[:10], message=str(message)[:10]):
                with self.assertRaises(chat.ChatInputError):
                    chat.check_request(instruction, message)

    def test_limits_are_inclusive(self):
        chat.check_request("x" * chat.MAX_INSTRUCTION, "y" * chat.MAX_MESSAGE)

    def test_path_is_only_built_for_the_six_friends(self):
        for bad in ("park", "../x", "", "PRIYA"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    chat.chat_path(bad)
        self.assertEqual(chat.chat_path("priya").name, "priya.jsonl")


class CleanReplyTest(unittest.TestCase):
    def test_strips_markdown(self):
        raw = "**Haha** nice!\n- first thing\n* second `thing`\n## Title\n1. numbered"
        self.assertEqual(chat.clean_reply(raw), "Haha nice!\nfirst thing\nsecond thing\nTitle\nnumbered")

    def test_keeps_plain_lines_and_apostrophes(self):
        self.assertEqual(chat.clean_reply("  I'm 5 * 3 sure \n\n next line "), "I'm 5 * 3 sure\nnext line")

    def test_empty_is_an_error(self):
        for raw in ("", "   ", "**", None, 3):
            with self.subTest(raw=raw):
                with self.assertRaises(chat.ChatError):
                    chat.clean_reply(raw)

    def test_long_reply_is_cut_at_a_word(self):
        out = chat.clean_reply("word " * 1000)
        self.assertLessEqual(len(out), chat.MAX_REPLY)
        self.assertTrue(out.endswith("word"))


class ContentsTest(unittest.TestCase):
    def msgs(self, roles):
        return [{"role": r, "text": f"t{i}", "at": ""} for i, r in enumerate(roles)]

    def test_drops_leading_friend_and_merges_same_role(self):
        got = chat.contents_for(self.msgs(["friend", "friend", "me", "me", "friend", "me"]))
        self.assertEqual(got, [("user", "t2\nt3"), ("model", "t4"), ("user", "t5")])

    def test_only_last_30(self):
        roles = ["me", "friend"] * 30
        got = chat.contents_for(self.msgs(roles))
        self.assertEqual(sum(text.count("t") for _, text in got), 30)
        self.assertEqual(got[0], ("user", "t30"))

    def test_empty(self):
        self.assertEqual(chat.contents_for([]), [])


class StorageTest(ChatTestCase):
    def test_missing_file_is_empty(self):
        self.assertEqual(chat.load_messages("priya"), [])

    def test_bad_lines_are_skipped_and_only_last_200_returned(self):
        self.say("omar", 250)
        with open(chat.chat_path("omar"), "a", encoding="utf-8") as f:
            f.write("not json\n" + json.dumps({"role": "robot", "text": "x"}) + "\n" + json.dumps({"role": "me", "text": " "}) + "\n")
        got = chat.load_messages("omar")
        self.assertEqual(len(got), 200)
        self.assertEqual(got[-1]["text"], "m249")
        self.assertEqual(got[0]["text"], "m50")

    def test_friends_do_not_share_files(self):
        self.say("priya", 2)
        self.assertEqual(chat.load_messages("jake"), [])


class SendTest(ChatTestCase):
    def test_appends_both_and_gives_history_to_the_model(self):
        self.say("priya", 2)
        seen = {}

        def fake(instruction, history):
            seen["instruction"], seen["history"] = instruction, history
            return "**Ha**, nice one!"

        res = chat.send("priya", "be Priya", "haha nice", generate=fake)

        self.assertEqual(res["reply"], "Ha, nice one!")
        self.assertEqual([m["role"] for m in res["messages"]], ["me", "friend"])
        self.assertEqual(seen["instruction"], "be Priya")
        self.assertEqual([m["text"] for m in seen["history"]], ["m0", "m1", "haha nice"])
        lines = chat.chat_path("priya").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 4)
        self.assertEqual(json.loads(lines[-1])["text"], "Ha, nice one!")

    def test_failed_model_writes_nothing(self):
        def boom(instruction, history):
            raise RuntimeError("429")

        with self.assertRaises(chat.ChatError):
            chat.send("priya", "x", "hi", generate=boom)
        self.assertFalse(chat.chat_path("priya").exists())

    def test_empty_reply_writes_nothing(self):
        with self.assertRaises(chat.ChatError):
            chat.send("priya", "x", "hi", generate=lambda i, h: "  ")
        self.assertFalse(chat.chat_path("priya").exists())

    def test_generate_reply_uses_system_instruction_and_conversation(self):
        calls = {}

        class Models:
            def generate_content(self, model, contents, config):
                calls.update(model=model, contents=contents, config=config)
                return mock.Mock(text="hello")

        client = mock.Mock(models=Models())
        with mock.patch("server.tutor._make_client", return_value=client):
            out = chat.generate_reply("be Priya", [{"role": "me", "text": "hi", "at": ""}, {"role": "friend", "text": "yo", "at": ""}])

        self.assertEqual(out, "hello")
        self.assertEqual(calls["model"], "gemini-2.5-flash")
        self.assertEqual(calls["config"].system_instruction, "be Priya")
        self.assertEqual([(c.role, c.parts[0].text) for c in calls["contents"]], [("user", "hi"), ("model", "yo")])


class AppendRepairTest(ChatTestCase):
    def test_append_after_a_half_written_line_starts_on_a_new_line(self):
        self.say("priya", 2)
        with open(chat.chat_path("priya"), "a", encoding="utf-8") as f:
            f.write('{"role": "me", "te')  # 덧붙이다 죽은 줄
        self.say("priya", 2, start=2)

        texts = [m["text"] for m in chat.read_all("priya")]
        self.assertEqual(texts, ["m0", "m1", "m2", "m3"])  # 새 줄이 깨진 줄에 붙지 않는다

    def test_append_to_missing_or_clean_file_adds_no_blank_line(self):
        self.say("priya", 1)
        self.say("priya", 1, start=1)
        self.assertEqual(len(chat.chat_path("priya").read_text(encoding="utf-8").splitlines()), 2)
        self.assertNotIn("\n\n", chat.chat_path("priya").read_text(encoding="utf-8"))


class ReplyClientTest(ChatTestCase):
    def test_record_usage_is_called_and_client_is_reused_with_timeout(self):
        response = mock.Mock(text="hello")
        client = mock.Mock()
        client.models.generate_content.return_value = response
        history = [{"role": "me", "text": "hi", "at": ""}]
        with mock.patch("server.tutor._make_client", return_value=client) as make, mock.patch("server.tutor.record_usage") as record:
            chat.generate_reply("be Priya", history)
            chat.generate_reply("be Priya", history)

        self.assertEqual(record.call_count, 2)
        record.assert_called_with(response)
        make.assert_called_once()
        self.assertEqual(make.call_args.kwargs["http_options"].timeout, chat.REPLY_TIMEOUT_MS)


class CloseTest(ChatTestCase):
    def model(self, calls):
        def generate_text(prompt):
            calls.append(prompt)
            return json.dumps(
                {
                    "fact_ops": [{"op": "ADD", "text": "The learner likes tea.", "importance": 3}],
                    "threads": [],
                    "self_story": [],
                    "jokes": [],
                    "episode": "They texted about tea.",
                }
            )

        return generate_text

    def test_nothing_without_learner_messages(self):
        self.assertIsNone(chat.prepare_close("priya"))
        chat.append_messages("priya", [{"role": "friend", "text": "hey!", "at": ""}])
        self.assertIsNone(chat.prepare_close("priya"))

    def test_chat_update_writes_a_chat_episode_then_nothing_until_new_messages(self):
        self.say("priya", 4)
        calls = []

        turns, total = chat.prepare_close("priya")
        self.assertEqual(total, 4)
        self.assertEqual(turns, [("me", "m0"), ("partner", "m1"), ("me", "m2"), ("partner", "m3")])
        self.assertTrue(chat.finish_close("priya", turns, total, generate_text=self.model(calls)))

        memory = partner_memory.load_memory("priya")
        self.assertEqual(memory["episodes"][0]["mode"], "chat")
        self.assertEqual(memory["facts"][0]["text"], "The learner likes tea.")
        self.assertIn("text chat", calls[0])
        self.assertIsNone(chat.prepare_close("priya"))

        self.say("priya", 2, start=4)
        turns2, total2 = chat.prepare_close("priya")
        self.assertEqual((turns2, total2), ([("me", "m4"), ("partner", "m5")], 6))

    def test_failed_update_keeps_the_messages_pending(self):
        self.say("priya", 2)
        turns, total = chat.prepare_close("priya")

        def boom(prompt):
            raise RuntimeError("down")

        self.assertFalse(chat.finish_close("priya", turns, total, generate_text=boom))
        self.assertIsNotNone(chat.prepare_close("priya"))

    def test_same_range_is_not_scheduled_twice_while_running(self):
        self.say("priya", 2)
        self.assertIsNotNone(chat.prepare_close("priya"))
        self.assertIsNone(chat.prepare_close("priya"))

    def test_overlapping_close_with_new_messages_waits_and_never_reprocesses(self):
        self.say("priya", 2)
        calls = []
        turns, total = chat.prepare_close("priya")
        self.say("priya", 2, start=2)  # 갱신이 도는 중에 새 메시지
        self.assertIsNone(chat.prepare_close("priya"))  # 같은 친구는 겹쳐 돌리지 않는다

        self.assertTrue(chat.finish_close("priya", turns, total, generate_text=self.model(calls)))
        turns2, total2 = chat.prepare_close("priya")  # 끝난 뒤 남은 메시지만 한 번 더
        self.assertEqual((turns2, total2), ([("me", "m2"), ("partner", "m3")], 4))
        self.assertTrue(chat.finish_close("priya", turns2, total2, generate_text=self.model(calls)))
        self.assertEqual(len(calls), 2)
        self.assertNotIn("m0", calls[1])
        self.assertEqual([e["mode"] for e in partner_memory.load_memory("priya")["episodes"]], ["chat", "chat"])

    def test_state_never_moves_backwards(self):
        chat._write_state("priya", 4)
        chat._write_state("priya", 2)
        self.assertEqual(chat._read_state("priya"), 4)
        chat._write_state("priya", 6)
        self.assertEqual(chat._read_state("priya"), 6)

    def test_only_the_last_60_messages_go_to_memory(self):
        self.say("priya", 100)
        turns, total = chat.prepare_close("priya")
        self.assertEqual((len(turns), total, turns[-1][1]), (60, 100, "m99"))


class PinDeleteTest(ChatTestCase):
    def ids(self, pid):
        return {m["text"]: m["id"] for m in chat.read_visible(pid)}

    def test_pin_persists_and_shows_in_view_even_when_old(self):
        self.say("priya", 250)
        ids = self.ids("priya")
        chat.set_pinned("priya", ids["m3"], True)
        view = chat.load_view("priya")
        self.assertEqual([m["text"] for m in view["pinned"]], ["m3"])
        self.assertEqual(len(view["messages"]), 200)
        self.assertNotIn("m3", [m["text"] for m in view["messages"]])  # 오래된 고정 메시지는 pinned로만 온다
        self.assertTrue(chat.marks_path("priya").exists())
        chat.set_pinned("priya", ids["m3"], False)
        self.assertEqual(chat.load_view("priya")["pinned"], [])

    def test_delete_persists_and_removes_from_view(self):
        self.say("priya", 4)
        ids = self.ids("priya")
        chat.set_pinned("priya", ids["m1"], True)
        chat.delete_message("priya", ids["m1"])
        view = chat.load_view("priya")
        self.assertEqual([m["text"] for m in view["messages"]], ["m0", "m2", "m3"])
        self.assertEqual(view["pinned"], [])  # 지우면 고정도 풀린다
        self.assertEqual(len(chat.read_all("priya")), 4)  # 파일의 줄은 그대로
        with self.assertRaises(KeyError):
            chat.set_pinned("priya", ids["m1"], True)
        with self.assertRaises(KeyError):
            chat.delete_message("priya", "nope")

    def test_deleted_messages_are_not_sent_to_the_model(self):
        self.say("priya", 4)  # me m0, friend m1, me m2, friend m3
        ids = self.ids("priya")
        chat.delete_message("priya", ids["m2"])
        seen = {}

        def fake(instruction, history):
            seen["history"] = history
            return "ok"

        chat.send("priya", "be Priya", "hello", generate=fake)
        texts = [m["text"] for m in seen["history"]]
        self.assertEqual(texts, ["m0", "m1", "m3", "hello"])
        self.assertNotIn("m2", [t for _, t in chat.contents_for(seen["history"])])
        self.assertNotIn("m2", "\n".join(t for _, t in chat.contents_for(seen["history"])))

    def test_deleted_messages_are_not_sent_to_memory(self):
        self.say("priya", 4)
        chat.delete_message("priya", self.ids("priya")["m2"])
        turns, total = chat.prepare_close("priya")
        self.assertEqual([t for _, t in turns], ["m0", "m1", "m3"])
        self.assertEqual(total, 4)

    def test_marks_survive_new_messages(self):
        self.say("priya", 2)
        chat.set_pinned("priya", self.ids("priya")["m0"], True)
        chat.send("priya", "x", "more", generate=lambda i, h: "yes")
        self.assertEqual([m["text"] for m in chat.load_view("priya")["pinned"]], ["m0"])

    def test_routes(self):
        from fastapi.testclient import TestClient

        from server import main

        client = TestClient(main.app)
        self.say("priya", 2)
        got = client.get("/api/chat/priya").json()
        mid = got["messages"][0]["id"]
        self.assertEqual(client.post("/api/chat/priya/pin", json={"id": mid, "pinned": True}).status_code, 200)
        self.assertEqual([m["text"] for m in client.get("/api/chat/priya").json()["pinned"]], ["m0"])
        self.assertEqual(client.post("/api/chat/priya/pin", json={"id": mid}).status_code, 400)
        self.assertEqual(client.post("/api/chat/priya/delete", json={"id": mid}).status_code, 200)
        self.assertEqual([m["text"] for m in client.get("/api/chat/priya").json()["messages"]], ["m1"])
        self.assertEqual(client.post("/api/chat/priya/delete", json={"id": mid}).status_code, 404)
        self.assertEqual(client.post("/api/chat/park/delete", json={"id": mid}).status_code, 400)


if __name__ == "__main__":
    unittest.main()

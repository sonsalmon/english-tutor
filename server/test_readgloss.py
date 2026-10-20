import json
import os
import socket
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import readgloss

NOW = datetime(2026, 10, 20, 9, 0)


def ms(dt):
    return int(dt.timestamp() * 1000)


STATE = {
    "known": {"easy": {"ts": 1}},
    "saved": {
        "indeed": {"word": "Indeed", "gloss": "참으로", "ts": ms(NOW - timedelta(days=1)), "review": {"done": False}},
        "finished": {"word": "finished", "gloss": "끝난", "ts": ms(NOW), "review": {"done": True}},
    },
    "history": [
        {"lemma": "haphazard", "gloss": "계획성 없는", "ts": ms(NOW - timedelta(hours=1))},
        {"lemma": "easy", "gloss": "쉬운", "ts": ms(NOW - timedelta(hours=2))},
        {"lemma": "ancient", "gloss": "오래된", "ts": ms(NOW - timedelta(days=30))},
        {"lemma": "mitigate", "gloss": "완화하다\n(위험을)", "ts": ms(NOW - timedelta(days=2))},
    ],
    "phrases": {},
}
DICT_FOUND = {
    "found": True,
    "lemma": "leverage",
    "gloss": "영향력",
    "mine": {"ko": "활용하다"},
    "entries": [
        {
            "headword": "leverage",
            "senses": [
                {"pos": "명사", "num": 1, "text": "영향력, 세력", "examples": []},
                {"pos": "명사", "num": 2, "text": "〔물리〕 지레의 작용; 지렉대", "examples": []},
                {"pos": "타동사", "num": 1, "text": "English only", "examples": []},
                {"pos": "타동사", "num": 2, "text": "영향력", "examples": []},
                {"pos": "타동사", "num": 3, "text": "빚을 이용해 투자하다", "examples": []},
                {"pos": "타동사", "num": 4, "text": "효과를 높이다", "examples": []},
            ],
        }
    ],
}
REVIEW = {"due": [{"type": "word", "key": "leverage", "gloss": "활용하다"}, {"type": "phrase", "key": "abc123abc123"}]}


class PickPracticeWordsTest(unittest.TestCase):
    def test_review_then_recent_lookups_then_saved_without_known_old_or_done(self):
        words = readgloss.pick_practice_words(STATE, REVIEW, NOW)

        self.assertEqual([w["lemma"] for w in words], ["leverage", "haphazard", "mitigate", "indeed"])
        self.assertEqual([w["source"] for w in words], ["review", "lookup", "lookup", "saved"])
        self.assertEqual(words[2]["gloss"], "완화하다 (위험을)")

    def test_many_due_reviews_leave_room_for_recent_lookups(self):
        review = {"due": [{"type": "word", "key": f"review{c}", "gloss": ""} for c in "abcdef"]}

        words = readgloss.pick_practice_words(STATE, review, NOW)

        self.assertEqual([w["lemma"] for w in words], ["reviewa", "reviewb", "reviewc", "haphazard", "mitigate"])

    def test_limit(self):
        self.assertEqual(len(readgloss.pick_practice_words(STATE, REVIEW, NOW, limit=2)), 2)


class WordsUsedTest(unittest.TestCase):
    def test_only_learner_lines_and_common_inflections_count(self):
        transcript = "**Partner:** Can you leverage it?\n**Me:** We mitigated it and I am studying.\n**Me:** I use it.\n"

        used = readgloss.words_used(transcript, ["mitigate", "study", "use", "leverage", "user"])

        self.assertEqual(used, ["mitigate", "study", "use"])

    def test_verbatim_counts_when_captions_missed_the_learner(self):
        transcript = "**Partner:** Hello there.\n"

        used = readgloss.words_used(transcript, ["mitigate", "leverage"], "Yesterday we mitigated a big risk.")

        self.assertEqual(used, ["mitigate"])

    def test_d_only_after_e_and_doubled_consonants(self):
        used = readgloss.words_used("**Me:** I got a card. We stopped and used it.", ["car", "stop", "use"])

        self.assertEqual(used, ["stop", "use"])

    def test_y_and_e_endings(self):
        self.assertEqual(readgloss.words_used("**Me:** It applies. I'm using it.", ["apply", "use"]), ["apply", "use"])


class PushOpsTest(unittest.TestCase):
    def test_single_word_goes_to_word_list_and_phrases_to_phrase_list(self):
        tutoring = {
            "vocab": [{"word": "Leverage", "meaning_ko": "활용하다"}, {"word": "circle back", "meaning_ko": "다시 논의하다"}, {"word": ""}],
            "corrections": [
                {"said": "I am agree", "better": "I agree", "why": "be동사를 빼요."},
                {"better": "  "},
                {"said": "엠에스", "better": "Ms.", "why": "발음"},
            ],
        }

        ops = readgloss.push_ops(tutoring, "English Tutor 통화 2026-10-20")

        self.assertEqual(ops[0], {"op": "save", "lemma": "leverage", "word": "Leverage", "gloss": "활용하다", "sentence": "", "url": ""})
        self.assertEqual([(o["op"], o.get("text")) for o in ops[1:]], [("save-phrase", "circle back"), ("save-phrase", "I agree")])
        self.assertTrue(all(o.get("kind", "expression") == "expression" for o in ops))


class CompactLookupTest(unittest.TestCase):
    def test_compact_shape_keeps_four_short_korean_senses(self):
        out = readgloss.compact_lookup("Leverage", DICT_FOUND)

        self.assertEqual(
            out,
            {"word": "Leverage", "lemma": "leverage", "gloss": "영향력", "senses": ["활용하다", "영향력", "지레의 작용", "빚을 이용해 투자하다"], "pos": "명사"},
        )

    def test_dictionary_markup_and_usage_notes_are_not_meanings(self):
        # 2026-10-20 실제 macOS 사전 응답(join): gloss가 문형 조각이고 유의어 줄(◇)이 섞여 있다.
        join = {
            "found": True,
            "lemma": "join",
            "gloss": "［join＋/join＋",
            "entries": [
                {
                    "headword": "join",
                    "senses": [
                        {"pos": "동사, 타동사", "text": "［join＋〈목〉/join＋〈목〉＋『부사』］ …을 결합하다, 붙이다; 합병하다〔together, up〕"},
                        {"pos": "동사, 타동사", "text": "connect 어떤 중간 매체로 결합시킴 ◇ two rooms connected by telephone"},
                        {"pos": "동사, 타동사", "text": "〈모임·당·군대 등에〉 참가[가입]하다"},
                        {"pos": "명사", "text": "[불]1.행동력; 효력"},
                    ],
                }
            ],
        }

        out = readgloss.compact_lookup("join", join)

        self.assertEqual(out["gloss"], "…을 결합하다")
        self.assertEqual(out["senses"], ["…을 결합하다", "참가하다", "행동력"])

    def test_unknown_word_has_empty_meaning_and_no_pos(self):
        out = readgloss.compact_lookup("Zzzq", {"found": False, "lemma": "zzzq"})

        self.assertEqual(out, {"word": "Zzzq", "lemma": "zzzq", "gloss": "", "senses": []})


class FakeBridge(BaseHTTPRequestHandler):
    calls = []

    def log_message(self, *args):
        pass

    def _reply(self, body, status=200):
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        FakeBridge.calls.append(("GET", self.path, self.headers.get("Host"), self.headers.get("X-Bridge-Token"), None))
        if self.headers.get("X-Bridge-Token") != "secret":
            return self._reply({"error": "unauthorized"}, 401)
        self._reply({"/words": STATE, "/words/review": REVIEW, "/ping": {"ok": True}}.get(self.path, {}))

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeBridge.calls.append(("POST", self.path, self.headers.get("Host"), self.headers.get("X-Bridge-Token"), body))
        if self.headers.get("X-Bridge-Token") != "secret":
            return self._reply({"error": "unauthorized"}, 401)
        if self.path == "/dict":
            return self._reply(DICT_FOUND if body.get("word") == "leverage" else {"found": False})
        self._reply({"ok": True})


class BridgeClientTest(unittest.TestCase):
    def setUp(self):
        FakeBridge.calls = []
        self.server = HTTPServer(("127.0.0.1", 0), FakeBridge)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.token_file = Path(tmp.name) / "token"
        self.token_file.write_text("secret\n", encoding="utf-8")
        self.env(f"http://127.0.0.1:{self.server.server_port}", self.token_file)

    def env(self, url, token_file):
        patcher = mock.patch.dict(os.environ, {readgloss.URL_ENV: url, readgloss.TOKEN_FILE_ENV: str(token_file)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_practice_words_sends_token_and_pinned_host(self):
        words = readgloss.practice_words(NOW)

        self.assertEqual([w["lemma"] for w in words][:2], ["leverage", "haphazard"])
        self.assertEqual({c[2] for c in FakeBridge.calls}, {"127.0.0.1:47831"})
        self.assertEqual({c[3] for c in FakeBridge.calls}, {"secret"})

    def test_push_sends_each_op_and_counts(self):
        saved = readgloss.push_tutoring({"vocab": [{"word": "leverage", "meaning_ko": "활용하다"}], "corrections": []}, "t")

        self.assertEqual(saved, 1)
        self.assertEqual([c[:2] for c in FakeBridge.calls], [("GET", "/ping"), ("POST", "/words")])
        self.assertEqual(FakeBridge.calls[1][4]["lemma"], "leverage")

    def test_lookup_word_posts_to_dict_and_compacts(self):
        out = readgloss.lookup_word("leverage")

        self.assertEqual((out["word"], out["lemma"], out["gloss"], len(out["senses"])), ("leverage", "leverage", "영향력", 4))
        self.assertEqual(FakeBridge.calls[0][:2] + (FakeBridge.calls[0][4],), ("POST", "/dict", {"word": "leverage"}))
        self.assertEqual(readgloss.lookup_word("nothing")["senses"], [])

    def test_save_word_posts_save_op(self):
        self.assertTrue(readgloss.save_word("leverage", "Leverages", "활용하다", "We leverage it."))

        self.assertEqual(
            FakeBridge.calls[0][:2] + (FakeBridge.calls[0][4],),
            ("POST", "/words", {"op": "save", "lemma": "leverage", "word": "Leverages", "gloss": "활용하다", "sentence": "We leverage it.", "url": ""}),
        )

    def test_lookup_and_save_are_none_false_when_bridge_refuses_or_is_down(self):
        self.token_file.write_text("wrong", encoding="utf-8")
        self.assertIsNone(readgloss.lookup_word("leverage"))
        self.assertFalse(readgloss.save_word("leverage", "leverage", "", ""))

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            closed_port = s.getsockname()[1]
        self.env(f"http://127.0.0.1:{closed_port}", self.token_file)
        self.assertIsNone(readgloss.lookup_word("leverage"))
        self.assertFalse(readgloss.save_word("leverage", "leverage", "", ""))

    def test_wrong_token_is_skipped_quietly(self):
        self.token_file.write_text("wrong", encoding="utf-8")

        self.assertEqual(readgloss.practice_words(NOW), [])
        self.assertIsNone(readgloss.push_tutoring({"vocab": [{"word": "x", "meaning_ko": ""}]}, "t"))

    def test_truncated_reply_is_skipped_quietly(self):
        import http.client

        with mock.patch("urllib.request.urlopen", side_effect=http.client.IncompleteRead(b"{")):
            self.assertEqual(readgloss.practice_words(NOW), [])

    def test_missing_token_file_or_bridge_down_is_skipped_quietly(self):
        self.env(f"http://127.0.0.1:{self.server.server_port}", self.token_file.parent / "nope")
        self.assertEqual(readgloss.practice_words(NOW), [])
        self.assertEqual(FakeBridge.calls, [])

        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            closed_port = s.getsockname()[1]
        self.env(f"http://127.0.0.1:{closed_port}", self.token_file)
        self.assertEqual(readgloss.practice_words(NOW), [])
        self.assertIsNone(readgloss.push_tutoring({"vocab": [{"word": "x", "meaning_ko": ""}]}, "t"))


if __name__ == "__main__":
    unittest.main()

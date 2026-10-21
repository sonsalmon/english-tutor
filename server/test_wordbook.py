import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException

from server import main, readgloss, wordbook

STATE = {
    "saved": {
        "indeed": {"word": "Indeed", "gloss": "참으로", "ts": 30, "review": {"done": False}, "sentence": "private page text", "url": "https://x.test"},
        "finished": {"word": "finished", "gloss": "끝난", "ts": 20, "review": {"done": True}},
        "mitigate": {"word": "mitigate", "gloss": "완화하다", "ts": 10},
        "bad": "x",
    },
    "phrases": {
        "aaaaaaaaaaaa": {"text": "Circle  back later", "translation": "나중에 다시", "kind": "expression", "ts": 5, "url": "https://x.test"},
        "bbbbbbbbbbbb": {"text": "short shift", "translation": "짧은 근무", "kind": "expression", "ts": 9},
        "cccccccccccc": {"text": "   ", "translation": "", "ts": 8},
        "dddddddddddd": "x",
    },
}
REVIEW = {"due": [{"type": "word", "key": "mitigate"}, {"type": "phrase", "key": "bbbbbbbbbbbb"}]}


class BuildWordbookTest(unittest.TestCase):
    def test_words_newest_first_with_review_status(self):
        book = wordbook.build_wordbook(STATE, REVIEW)

        self.assertEqual([(w["lemma"], w["status"]) for w in book["words"]], [("indeed", "learning"), ("finished", "done"), ("mitigate", "due")])
        self.assertEqual(book["words"][0]["word"], "Indeed")
        self.assertEqual(book["words"][0]["gloss"], "참으로")

    def test_phrases_newest_first_and_blank_or_broken_dropped(self):
        book = wordbook.build_wordbook(STATE, None)

        self.assertEqual([p["text"] for p in book["phrases"]], ["short shift", "Circle back later"])
        self.assertEqual(book["phrases"][1]["gloss"], "나중에 다시")

    def test_reading_sentence_and_page_url_never_leave(self):
        book = wordbook.build_wordbook(STATE, REVIEW)

        for item in book["words"] + book["phrases"]:
            self.assertFalse({"sentence", "url"} & set(item))

    def test_empty_state(self):
        self.assertEqual(wordbook.build_wordbook({}, None), {"words": [], "phrases": []})


class WordbookEndpointTest(unittest.TestCase):
    def test_router_is_mounted(self):
        self.assertIn("/api/wordbook", {route.path for route in main.app.routes})

    def test_bridge_off_is_503(self):
        with mock.patch.object(readgloss, "bridge_snapshot", return_value=None):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(wordbook.wordbook_endpoint())

        self.assertEqual(ctx.exception.status_code, 503)

    def test_bridge_on_returns_the_book(self):
        with mock.patch.object(readgloss, "bridge_snapshot", return_value=(STATE, REVIEW)):
            body = asyncio.run(wordbook.wordbook_endpoint())

        self.assertEqual(len(body["words"]), 3)
        self.assertEqual(len(body["phrases"]), 2)


if __name__ == "__main__":
    unittest.main()

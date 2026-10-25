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


class FakeBridge:
    """readgloss 다리의 /words 연산 일부를 흉내 낸 메모리 저장소."""

    def __init__(self, state, alive=True):
        self.state = state
        self.alive = alive
        self.calls = []

    def __call__(self, method, path, body=None, timeout=1.5):
        self.calls.append((method, path, body))
        if not self.alive:
            return None
        if path == "/ping":
            return {"ok": True}
        if method == "GET":
            return self.state
        op = body["op"]
        if op == "unsave":
            self.state["saved"].pop(body["lemma"], None)
        elif op == "unsave-phrase":
            self.state["phrases"].pop(body["id"], None)
        elif op == "save":
            self.state["saved"][body["lemma"]] = {k: body[k] for k in ("word", "gloss", "sentence", "url")}
        elif op == "save-phrase":
            self.state["phrases"]["aaaaaaaaaaaa"] = {k: body[k] for k in ("text", "translation", "kind", "sentence", "url", "title")}
        elif op == "memo":
            target = self.state["saved"].get(body.get("lemma")) or self.state["phrases"].get(body.get("id"))
            target["memo"] = body["memo"]
        return self.state


def fresh_state():
    return {
        "saved": {"indeed": {"word": "Indeed", "gloss": "참으로", "sentence": "a page line", "url": "https://x.test", "memo": "메모"}},
        "phrases": {"aaaaaaaaaaaa": {"text": "Circle back later", "translation": "나중에 다시", "kind": "expression", "url": "https://x.test", "title": "t"}},
    }


class DeleteRestoreTest(unittest.TestCase):
    def test_delete_word_removes_from_store_and_returns_snapshot(self):
        bridge = FakeBridge(fresh_state())
        with mock.patch.object(readgloss, "_request", bridge):
            body = asyncio.run(wordbook.delete_endpoint("word", "Indeed"))

        self.assertNotIn("indeed", bridge.state["saved"])
        self.assertEqual(body["snapshot"]["type"], "word")
        self.assertEqual(body["snapshot"]["key"], "indeed")
        self.assertEqual(body["snapshot"]["sentence"], "a page line")

    def test_delete_then_restore_word_round_trip_keeps_memo(self):
        bridge = FakeBridge(fresh_state())
        with mock.patch.object(readgloss, "_request", bridge):
            snap = asyncio.run(wordbook.delete_endpoint("word", "indeed"))["snapshot"]
            asyncio.run(wordbook.restore_endpoint(wordbook.RestoreBody(snapshot=snap)))

        self.assertEqual(bridge.state["saved"]["indeed"]["gloss"], "참으로")
        self.assertEqual(bridge.state["saved"]["indeed"]["url"], "https://x.test")
        self.assertEqual(bridge.state["saved"]["indeed"]["memo"], "메모")

    def test_delete_then_restore_phrase_round_trip(self):
        bridge = FakeBridge(fresh_state())
        with mock.patch.object(readgloss, "_request", bridge):
            snap = asyncio.run(wordbook.delete_endpoint("phrase", "aaaaaaaaaaaa"))["snapshot"]
            self.assertEqual(bridge.state["phrases"], {})
            asyncio.run(wordbook.restore_endpoint(wordbook.RestoreBody(snapshot=snap)))

        self.assertEqual(bridge.state["phrases"]["aaaaaaaaaaaa"]["text"], "Circle back later")
        self.assertEqual(bridge.state["phrases"]["aaaaaaaaaaaa"]["kind"], "expression")

    def test_missing_item_is_404_and_bad_id_is_400(self):
        bridge = FakeBridge(fresh_state())
        with mock.patch.object(readgloss, "_request", bridge):
            with self.assertRaises(HTTPException) as missing:
                asyncio.run(wordbook.delete_endpoint("word", "nothere"))
            with self.assertRaises(HTTPException) as bad:
                asyncio.run(wordbook.delete_endpoint("phrase", "../x"))
            with self.assertRaises(HTTPException) as kind:
                asyncio.run(wordbook.delete_endpoint("memo", "indeed"))

        self.assertEqual(missing.exception.status_code, 404)
        self.assertEqual(bad.exception.status_code, 400)
        self.assertEqual(kind.exception.status_code, 404)
        self.assertEqual(len(bridge.state["saved"]), 1)

    def test_bridge_off_is_503_for_delete_and_restore(self):
        bridge = FakeBridge(fresh_state(), alive=False)
        with mock.patch.object(readgloss, "_request", bridge):
            with self.assertRaises(HTTPException) as d:
                asyncio.run(wordbook.delete_endpoint("word", "indeed"))
            with self.assertRaises(HTTPException) as r:
                asyncio.run(wordbook.restore_endpoint(wordbook.RestoreBody(snapshot={"type": "word", "key": "indeed", "word": "Indeed"})))

        self.assertEqual(d.exception.status_code, 503)
        self.assertEqual(r.exception.status_code, 503)

    def test_restore_rejects_unknown_snapshot(self):
        with mock.patch.object(readgloss, "_request", FakeBridge(fresh_state())):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(wordbook.restore_endpoint(wordbook.RestoreBody(snapshot={"type": "other"})))

        self.assertEqual(ctx.exception.status_code, 400)

    def test_routes_are_mounted(self):
        paths = {(m, r.path) for r in main.app.routes for m in getattr(r, "methods", ())}
        self.assertIn(("DELETE", "/api/wordbook/{kind}/{key}"), paths)
        self.assertIn(("POST", "/api/wordbook/restore"), paths)


if __name__ == "__main__":
    unittest.main()

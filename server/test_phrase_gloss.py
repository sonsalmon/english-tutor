import asyncio
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException

from server import main, phrase_gloss


class FakeRequest:
    def __init__(self, body, content_type="application/json"):
        self._body = body
        self.headers = {"content-type": content_type}

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


def call(body, **kwargs):
    return asyncio.run(phrase_gloss.phrase_gloss_endpoint(FakeRequest(body, **kwargs)))


class PhraseGlossTest(unittest.TestCase):
    def setUp(self):
        phrase_gloss._CACHE.clear()

    def test_router_is_mounted_on_the_app(self):
        paths = {route.path for route in main.app.routes}

        self.assertIn("/api/phrase/gloss", paths)

    def test_returns_model_gloss_and_normalizes_input(self):
        fake = mock.Mock(return_value=json.dumps({"gloss": " 미루다 "}, ensure_ascii=False))
        with mock.patch("server.tutor.make_generate_text", return_value=fake):
            res = call({"text": "  put   off "})

        self.assertEqual(res, {"gloss": "미루다"})
        self.assertIn('"put off"', fake.call_args.args[0])

    def test_second_request_comes_from_cache(self):
        fake = mock.Mock(return_value='{"gloss": "미루다"}')
        with mock.patch("server.tutor.make_generate_text", return_value=fake):
            call({"text": "put off"})
            call({"text": "Put Off"})

        fake.assert_called_once()

    def test_model_failure_gives_empty_gloss_and_is_not_cached(self):
        broken = mock.Mock(side_effect=RuntimeError("model down"))
        with mock.patch("server.tutor.make_generate_text", return_value=broken):
            self.assertEqual(call({"text": "put off"}), {"gloss": ""})
        good = mock.Mock(return_value='{"gloss": "미루다"}')
        with mock.patch("server.tutor.make_generate_text", return_value=good):
            self.assertEqual(call({"text": "put off"}), {"gloss": "미루다"})

    def test_client_construction_failure_gives_empty_gloss(self):
        with mock.patch("server.tutor.make_generate_text", side_effect=RuntimeError("no credentials")):
            self.assertEqual(call({"text": "put off"}), {"gloss": ""})

    def test_unparseable_or_wrong_shape_model_output_gives_empty_gloss(self):
        for raw in ("not json", "[]", '{"gloss": 3}', '{"other": "x"}'):
            with self.subTest(raw=raw), mock.patch("server.tutor.make_generate_text", return_value=mock.Mock(return_value=raw)):
                self.assertEqual(call({"text": "put off"}), {"gloss": ""})

    def test_long_gloss_is_truncated(self):
        fake = mock.Mock(return_value=json.dumps({"gloss": "가" * 200}))
        with mock.patch("server.tutor.make_generate_text", return_value=fake):
            self.assertEqual(len(call({"text": "put off"})["gloss"]), phrase_gloss.MAX_GLOSS_CHARS)

    def test_rejects_bad_input_without_calling_the_model(self):
        bad = [
            {"text": "a"},
            {"text": "x" * 81},
            {"text": "12 34"},
            {"text": 5},
            {},
        ]
        with mock.patch("server.tutor.make_generate_text") as make:
            for body in bad:
                with self.subTest(body=body), self.assertRaises(HTTPException) as ctx:
                    call(body)
                self.assertEqual(ctx.exception.status_code, 400)
            make.assert_not_called()

    def test_boundary_lengths_are_accepted(self):
        fake = mock.Mock(return_value='{"gloss": "뜻"}')
        with mock.patch("server.tutor.make_generate_text", return_value=fake):
            self.assertEqual(call({"text": "up"}), {"gloss": "뜻"})
            self.assertEqual(call({"text": "a" * 80}), {"gloss": "뜻"})

    def test_rejects_non_json_content_type_and_non_object_body(self):
        with self.assertRaises(HTTPException) as ctx:
            call({"text": "put off"}, content_type="text/plain")
        self.assertEqual(ctx.exception.status_code, 415)
        for body in (["put off"], ValueError("bad json")):
            with self.subTest(body=body), self.assertRaises(HTTPException) as ctx:
                call(body)
            self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()

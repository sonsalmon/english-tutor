import json
import os
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import youtube  # noqa: E402

STEM = "2026-10-20-101500"

_BODY = json.dumps(
    {
        "items": [
            {
                "id": {"kind": "youtube#video", "videoId": "abc123"},
                "snippet": {
                    "title": "Weekend plans &amp; small talk &#39;101&#39;",
                    "channelTitle": "Real English &amp; Co",
                    "publishedAt": "2024-01-02T03:04:05Z",
                    "thumbnails": {"default": {"url": "http://d"}, "medium": {"url": "http://m"}},
                },
            },
            {"id": {"kind": "youtube#channel"}, "snippet": {"title": "no video id"}},
            {"id": {"videoId": "def456"}, "snippet": {"title": "Plain", "channelTitle": "C"}},
        ]
    }
)


class FakeHttp:
    def __init__(self, status=200, body=_BODY):
        self.status, self.body, self.urls = status, body, []

    def __call__(self, url):
        self.urls.append(url)
        return self.status, self.body


class SearchTest(unittest.TestCase):
    def test_request_parameters(self):
        http = FakeHttp()
        youtube.search("coworkers small talk", key="K", http=http)
        self.assertEqual(len(http.urls), 1)
        parsed = urllib.parse.urlparse(http.urls[0])
        self.assertEqual(parsed.netloc + parsed.path, "www.googleapis.com/youtube/v3/search")
        q = dict(urllib.parse.parse_qsl(parsed.query))
        self.assertEqual(
            q,
            {
                "part": "snippet",
                "type": "video",
                "maxResults": "5",
                "relevanceLanguage": "en",
                "regionCode": "US",
                "safeSearch": "moderate",
                "videoEmbeddable": "true",
                "q": "coworkers small talk",
                "key": "K",
            },
        )

    def test_parse_and_unescape(self):
        clips = youtube.search("q", key="K", http=FakeHttp())
        self.assertEqual([c["id"] for c in clips], ["abc123", "def456"])
        self.assertEqual(clips[0]["title"], "Weekend plans & small talk '101'")
        self.assertEqual(clips[0]["channel"], "Real English & Co")
        self.assertEqual(clips[0]["thumbnail"], "http://m")
        self.assertEqual(clips[0]["published"], "2024-01-02T03:04:05Z")
        self.assertEqual(clips[1]["thumbnail"], "")

    def test_quota_error(self):
        body = json.dumps({"error": {"errors": [{"reason": "quotaExceeded"}]}})
        with self.assertRaises(youtube.YouTubeQuotaError) as cm:
            youtube.search("q", key="SECRETKEY", http=FakeHttp(403, body))
        self.assertNotIn("SECRETKEY", str(cm.exception))

    def test_http_error_and_bad_body(self):
        with self.assertRaises(youtube.YouTubeHttpError) as cm:
            youtube.search("q", key="K", http=FakeHttp(400, "{}"))
        self.assertEqual(cm.exception.status, 400)
        self.assertNotIsInstance(cm.exception, youtube.YouTubeQuotaError)
        with self.assertRaises(youtube.YouTubeHttpError):
            youtube.search("q", key="K", http=FakeHttp(200, "not json"))


class LanguageFilterTest(unittest.TestCase):
    def test_other_language_titles_dropped(self):
        titles = [
            "Learn Turkish in 10 minutes",
            "SPANISH small talk",
            "Real English chat",
            "Thai food vlog",
            "Nothing about Thailand-free",
            "Korean Air tips",
        ]
        body = json.dumps(
            {"items": [{"id": {"videoId": f"v{i}"}, "snippet": {"title": t}} for i, t in enumerate(titles)]}
        )
        got = youtube.search("q", key="K", http=FakeHttp(body=body))
        self.assertEqual([c["title"] for c in got], ["Real English chat", "Nothing about Thailand-free"])


class ClipsForCallTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {"CLIPS_DIR": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_cache_hit_makes_no_second_request(self):
        http = FakeHttp()
        first = youtube.clips_for_call(STEM, "q", key="K", http=http)
        self.assertTrue((Path(self._tmp.name) / f"{STEM}.json").is_file())
        # 두 번째는 키가 없어도, 다른 검색어여도 캐시를 돌려준다.
        second = youtube.clips_for_call(STEM, "other", key=None, http=http)
        self.assertEqual(first, second)
        self.assertEqual(len(http.urls), 1)

    def test_missing_key(self):
        http = FakeHttp()
        with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}), mock.patch.object(
            youtube, "KEY_FILE", Path(self._tmp.name) / "nope"
        ):
            self.assertIsNone(youtube.api_key())
            with self.assertRaises(youtube.YouTubeKeyMissing):
                youtube.clips_for_call(STEM, "q", http=http)
        self.assertEqual(http.urls, [])

    def test_api_key_sources(self):
        keyfile = Path(self._tmp.name) / "key"
        keyfile.write_text("FILEKEY\n", encoding="utf-8")
        with mock.patch.object(youtube, "KEY_FILE", keyfile):
            with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": "ENVKEY"}):
                self.assertEqual(youtube.api_key(), "ENVKEY")
            with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}):
                self.assertEqual(youtube.api_key(), "FILEKEY")

    def test_errors_are_not_cached(self):
        with self.assertRaises(youtube.YouTubeHttpError):
            youtube.clips_for_call(STEM, "q", key="K", http=FakeHttp(500, "x"))
        self.assertFalse((Path(self._tmp.name) / f"{STEM}.json").exists())

    def test_bad_stem_rejected(self):
        http = FakeHttp()
        for bad in ("../x", "2026-10-20-101500.md", "a/b", "2026-10-20-101500\n", ""):
            with self.assertRaises(ValueError):
                youtube.clips_for_call(bad, "q", key="K", http=http)
        self.assertEqual(http.urls, [])

    def test_empty_query_skips_search(self):
        http = FakeHttp()
        self.assertEqual(youtube.clips_for_call(STEM, "  ", key="K", http=http), [])
        self.assertEqual(http.urls, [])


if __name__ == "__main__":
    unittest.main()

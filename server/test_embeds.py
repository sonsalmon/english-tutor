import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import clipdb, embeds, youtube

KEY = "AIzaSy-test-key-do-not-print"


def vid(n):
    return f"vid{n:08d}"


class Api:
    """Fake of the YouTube videos.list call. `blocked` ids come back embeddable=false, `missing` ids are left out."""

    def __init__(self, blocked=(), missing=(), status=200, body=None):
        self.blocked, self.missing, self.status, self.body = set(blocked), set(missing), status, body
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if self.body is not None:
            return self.status, self.body
        query = dict(p.split("=", 1) for p in url.split("?", 1)[1].split("&"))
        ids = query["id"].replace("%2C", ",").split(",")
        items = [
            {"id": i, "status": {"embeddable": i not in self.blocked, "privacyStatus": "public"}} for i in ids if i not in self.missing
        ]
        return self.status, json.dumps({"items": items})

    def requested(self):
        return [u.split("id=", 1)[1].split("&")[0].replace("%2C", ",").split(",") for u in self.urls]


class EmbedsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.cache = self.root / "cache" / "embed.json"
        env = mock.patch.dict(os.environ, {"EMBED_CACHE_PATH": str(self.cache), "YOUTUBE_API_KEY": KEY})
        env.start()
        self.addCleanup(env.stop)

    def fake(self, api):
        patcher = mock.patch.object(embeds, "_http_get", api)
        patcher.start()
        self.addCleanup(patcher.stop)
        return api

    def test_unknown_ids_are_checked_in_batches_of_fifty_and_cached(self):
        api = self.fake(Api(blocked={vid(3), vid(77)}))
        ids = [vid(n) for n in range(120)]

        ok = embeds.playable(ids)

        self.assertEqual([len(r) for r in api.requested()], [50, 50, 20])
        self.assertEqual(ok, set(ids) - {vid(3), vid(77)})
        self.assertIn("part=status", api.urls[0])
        saved = json.loads(self.cache.read_text(encoding="utf-8"))["videos"]
        self.assertEqual((saved[vid(3)]["embeddable"], saved[vid(4)]["embeddable"]), (False, True))

    def test_known_ids_are_not_asked_again_and_only_new_ones_are(self):
        api = self.fake(Api(blocked={vid(1)}))
        embeds.playable([vid(1), vid(2)])
        self.assertEqual(len(api.urls), 1)

        again = embeds.playable([vid(1), vid(2)])
        self.assertEqual((len(api.urls), again), (1, {vid(2)}))

        embeds.playable([vid(1), vid(2), vid(3)])
        self.assertEqual(api.requested()[-1], [vid(3)])

    def test_deleted_or_private_videos_missing_from_the_answer_are_not_playable(self):
        self.fake(Api(missing={vid(5)}))
        self.assertEqual(embeds.playable([vid(5), vid(6)]), {vid(6)})

    def test_api_failure_lets_videos_through_without_caching_them(self):
        api = self.fake(Api(status=403, body=json.dumps({"error": {"errors": [{"reason": "quotaExceeded"}]}})))
        self.assertEqual(embeds.playable([vid(1)]), {vid(1)})
        self.assertFalse(self.cache.exists())
        api.status, api.body = 200, None
        api.blocked = {vid(1)}
        self.assertEqual(embeds.playable([vid(1)]), set())

    def test_network_error_and_garbage_bodies_fail_open_and_never_log_the_key(self):
        def boom(url):
            raise youtube.YouTubeHttpError("\ub124\ud2b8\uc6cc\ud06c \uc624\ub958(URLError)")

        with mock.patch.object(embeds, "_http_get", boom), self.assertLogs("server.embeds", level="WARNING") as logs:
            self.assertEqual(embeds.playable([vid(1)]), {vid(1)})
        self.fake(Api(body="not json"))
        with self.assertLogs("server.embeds", level="WARNING") as more:
            self.assertEqual(embeds.playable([vid(2)]), {vid(2)})
        self.assertNotIn(KEY, "\n".join(logs.output + more.output))
        self.assertFalse(self.cache.exists())

    def test_without_a_key_nothing_is_fetched_and_everything_plays(self):
        api = self.fake(Api())
        with mock.patch.object(youtube, "api_key", return_value=None):
            self.assertEqual(embeds.playable([vid(1), vid(2)]), {vid(1), vid(2)})
        self.assertEqual(api.urls, [])

    def test_the_key_comes_from_the_youtube_key_file_reader(self):
        api = self.fake(Api())
        with mock.patch.dict(os.environ, {"YOUTUBE_API_KEY": ""}), mock.patch.object(youtube, "KEY_FILE", self.root / "key"):
            (self.root / "key").write_text(KEY + "\n", encoding="utf-8")
            embeds.playable([vid(1)])
        self.assertIn(f"key={KEY}", api.urls[0])

    def test_mark_blocked_is_remembered_and_survives_a_new_check(self):
        api = self.fake(Api())
        self.assertTrue(embeds.mark_blocked(vid(9)))

        self.assertEqual(embeds.playable([vid(9), vid(10)]), {vid(10)})
        self.assertEqual(api.requested(), [[vid(10)]])
        self.assertEqual(json.loads(self.cache.read_text(encoding="utf-8"))["videos"][vid(9)]["source"], "client")

    def test_mark_blocked_rejects_bad_ids(self):
        for bad in ("", "a/b", "x" * 40, "short", None, 7):
            self.assertFalse(embeds.mark_blocked(bad), bad)
        self.assertFalse(self.cache.exists())

    def test_bad_ids_are_ignored_and_empty_input_makes_no_request(self):
        api = self.fake(Api())
        self.assertEqual(embeds.playable(["", "a b", None, "x" * 40]), set())
        self.assertEqual(api.urls, [])

    def test_default_cache_sits_next_to_the_caption_db_not_inside_it(self):
        with mock.patch.dict(os.environ, {"CLIPDB_PATH": str(self.root / "clipdb" / "captions.db")}):
            os.environ.pop("EMBED_CACHE_PATH")
            self.assertEqual(embeds.cache_path(), self.root / "clipdb" / "embed-cache.json")

    def test_caption_db_is_never_modified(self):
        db = self.root / "captions.db"
        conn = clipdb.connect(db)
        clipdb.upsert_channel(conn, "@c", "C", "tv")
        conn.close()
        before = hashlib.sha256(db.read_bytes()).hexdigest()
        with mock.patch.dict(os.environ, {"CLIPDB_PATH": str(db)}):
            self.fake(Api(blocked={vid(1)}))
            embeds.playable([vid(1), vid(2)])
            embeds.mark_blocked(vid(3))
        self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)

    def test_a_broken_cache_file_is_treated_as_empty(self):
        self.cache.parent.mkdir(parents=True)
        self.cache.write_text("{not json", encoding="utf-8")
        api = self.fake(Api())
        self.assertEqual(embeds.playable([vid(1)]), {vid(1)})
        self.assertEqual(len(api.urls), 1)



class EmbedsLockTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cache = Path(tmp.name) / "embed.json"
        env = mock.patch.dict(os.environ, {"EMBED_CACHE_PATH": str(self.cache), "YOUTUBE_API_KEY": KEY})
        env.start()
        self.addCleanup(env.stop)

    def test_the_lock_is_free_while_the_network_call_runs(self):
        seen = []
        inner = Api()

        def http(url):
            free = embeds._LOCK.acquire(blocking=False)
            if free:
                embeds._LOCK.release()
            seen.append(free)
            return inner(url)

        with mock.patch.object(embeds, "_http_get", http):
            embeds.playable([vid(1), vid(2)])

        self.assertEqual(seen, [True])

    def test_a_video_blocked_by_the_player_during_the_check_stays_blocked(self):
        inner = Api()

        def http(url):
            embeds.mark_blocked(vid(2))
            return inner(url)

        with mock.patch.object(embeds, "_http_get", http):
            got = embeds.playable([vid(1), vid(2)])

        self.assertEqual(got, {vid(1)})
        with mock.patch.object(embeds, "_http_get", Api()):
            self.assertEqual(embeds.playable([vid(1), vid(2)]), {vid(1)})


if __name__ == "__main__":
    unittest.main()

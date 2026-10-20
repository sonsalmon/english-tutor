#!/usr/bin/env python3
"""고른 유튜브 채널의 영어 자막을 받아 로컬 SQLite FTS5 DB(CLIPDB_PATH)를 채운다.

영상 id는 YouTube Data API v3로, 자막은 yt-dlp로 받는다(영상은 받지 않는다).
이어받기: videos에 status ok/no_captions로 남은 영상은 건너뛴다.
유튜브에 부담을 주지 않도록 요청마다 쉬고, HTTP 429가 나오면 전체를 멈춘다(종료 코드 2).
"""

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from server import clipdb  # noqa: E402

CHANNELS_FILE = ROOT / "server" / "clipdb_channels.json"
KEY_FILE = Path.home() / ".config" / "english-tutor" / "youtube-api-key"
API = "https://www.googleapis.com/youtube/v3/"
CAPTION_LANGS = ["en", "en-US", "en-GB", "en-orig"]
MAX_CONSECUTIVE_ERRORS = 5
EXIT_OK, EXIT_FATAL, EXIT_RATE_LIMITED, EXIT_BLOCKED = 0, 1, 2, 3


class RateLimited(Exception):
    pass


class Blocked(Exception):
    pass


def load_api_key() -> str:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key and KEY_FILE.is_file():
        key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise SystemExit(f"YouTube API 키가 없습니다: 환경변수 YOUTUBE_API_KEY 또는 {KEY_FILE}")
    return key


def api_get(key: str, path: str, **params: Any) -> Dict[str, Any]:
    """Data API 호출. 키가 로그에 새지 않도록 오류에는 상태 코드와 이유만 담는다."""
    url = API + path + "?" + urllib.parse.urlencode({**params, "key": key})
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited(f"YouTube Data API가 HTTP 429를 돌려줬습니다 ({path}).")
        reason = ""
        try:
            reason = json.load(e)["error"]["errors"][0]["reason"]
        except Exception:
            pass
        raise RuntimeError(f"YouTube Data API 오류 {path}: HTTP {e.code} {reason}".strip()) from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"YouTube Data API 연결 실패 {path}: {e.reason}") from None


def parse_duration(iso: Optional[str]) -> Optional[int]:
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


def list_video_ids(key: str, handle: str, count: int) -> Tuple[Optional[str], List[str]]:
    """채널 제목과 최신 영상 id를 count개까지(최신순) 돌려준다."""
    ch = api_get(key, "channels", part="snippet,contentDetails", forHandle=handle)
    items = ch.get("items") or []
    if not items:
        return None, []
    uploads = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    title = items[0]["snippet"]["title"]
    ids: List[str] = []
    token: Optional[str] = None
    while len(ids) < count:
        params: Dict[str, Any] = {"part": "contentDetails", "playlistId": uploads, "maxResults": min(50, count - len(ids))}
        if token:
            params["pageToken"] = token
        page = api_get(key, "playlistItems", **params)
        ids.extend(i["contentDetails"]["videoId"] for i in page.get("items", []))
        token = page.get("nextPageToken")
        if not token:
            break
    return title, ids[:count]


def video_details(key: str, ids: List[str], handle: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(0, len(ids), 50):
        data = api_get(key, "videos", part="snippet,contentDetails", id=",".join(ids[i : i + 50]))
        by_id = {v["id"]: v for v in data.get("items", [])}
        for vid in ids[i : i + 50]:
            v = by_id.get(vid)
            if v is None:
                continue
            out.append(
                {
                    "id": vid,
                    "channel_handle": handle,
                    "title": v["snippet"].get("title"),
                    "published": v["snippet"].get("publishedAt"),
                    "duration_sec": parse_duration(v["contentDetails"].get("duration")),
                }
            )
    return out


class _Logger:
    """yt-dlp 메시지를 모아 429·봇 차단을 알아챈다. 화면에는 찍지 않는다."""

    def __init__(self) -> None:
        self.messages: List[str] = []

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        self.messages.append(msg)

    def error(self, msg: str) -> None:
        self.messages.append(msg)


def pick_caption_lang(manual: Dict[str, Any], auto: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """수동 자막을 먼저, 없으면 자동 자막을 고른다. (언어, 'manual'|'auto')"""
    for lang in CAPTION_LANGS:
        if lang in manual:
            return lang, "manual"
    for lang in ["en-orig", "en", "en-US", "en-GB"]:
        if lang in auto:
            return lang, "auto"
    return None, None


def _check_signals(text: str) -> None:
    low = text.lower()
    if "429" in low or "too many requests" in low:
        raise RateLimited("yt-dlp가 HTTP 429(Too Many Requests)를 만났습니다.")
    if "confirm you" in low and "bot" in low:
        raise Blocked("유튜브가 봇 확인을 요구합니다.")


def fetch_captions(ydl: Any, video_id: str, cache_dir: Path, logger: _Logger) -> Tuple[str, Optional[str], List[Dict[str, Any]]]:
    """영상 한 편의 자막을 받아 (status, kind, segments)를 돌려준다."""
    import yt_dlp

    logger.messages.clear()
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        info = ydl.extract_info(url, download=False)
        lang, kind = pick_caption_lang(info.get("subtitles") or {}, info.get("automatic_captions") or {})
        if lang is None:
            return "no_captions", None, []
        ydl.params["subtitleslangs"] = [lang]
        done = ydl.process_ie_result(info, download=True)
    except yt_dlp.utils.DownloadError as e:
        _check_signals(str(e) + " ".join(logger.messages))
        raise
    _check_signals(" ".join(logger.messages))
    sub = (done.get("requested_subtitles") or {}).get(lang) or {}
    path = Path(sub.get("filepath") or cache_dir / f"{video_id}.{lang}.vtt")
    if not path.is_file():
        raise RuntimeError(f"자막 파일이 없습니다: {' '.join(logger.messages)[:200]}")
    segments = clipdb.parse_vtt(path.read_text(encoding="utf-8", errors="replace"), rolling=(kind == "auto"))
    if not segments:
        return "no_captions", kind, []
    return "ok", kind, segments


def make_ydl(cache_dir: Path, logger: _Logger, request_sleep: float, subtitle_sleep: float) -> Any:
    import yt_dlp

    return yt_dlp.YoutubeDL(
        {
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": CAPTION_LANGS,
            "subtitlesformat": "vtt",
            "outtmpl": str(cache_dir / "%(id)s"),
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": logger,
            "sleep_interval_requests": request_sleep,
            "sleep_interval_subtitles": subtitle_sleep,
            "retries": 1,
            "extractor_retries": 1,
            "retry_sleep_functions": {"http": lambda n: 10 * (n + 1), "extractor": lambda n: 10 * (n + 1)},
        }
    )


def select_channels(all_channels: List[Dict[str, str]], wanted: Optional[str]) -> List[Dict[str, str]]:
    if not wanted:
        return all_channels
    by_handle = {c["handle"].lower().lstrip("@"): c for c in all_channels}
    chosen = []
    for raw in wanted.split(","):
        key = raw.strip().lower().lstrip("@")
        if key not in by_handle:
            raise SystemExit(f"채널 목록에 없는 핸들입니다: {raw.strip()}")
        chosen.append(by_handle[key])
    return chosen


def run(args: argparse.Namespace) -> int:
    channels = select_channels(json.loads(CHANNELS_FILE.read_text(encoding="utf-8")), args.channels)
    db = Path(args.db) if args.db else clipdb.db_path()
    cache_dir = db.parent / "vtt"
    cache_dir.mkdir(parents=True, exist_ok=True)
    conn = clipdb.connect(db)
    per_channel = min(args.per_channel, args.limit_videos) if args.limit_videos else args.per_channel
    key = load_api_key()
    logger = _Logger()
    ydl = make_ydl(cache_dir, logger, args.request_sleep, args.subtitle_sleep)

    counts = {"ok": 0, "no_captions": 0, "error": 0, "skipped": 0, "segments": 0}
    consecutive_errors = 0
    try:
        for ch in channels:
            handle = ch["handle"]
            title, ids = list_video_ids(key, handle, per_channel)
            if title is None:
                print(f"[{handle} 0/0] 채널을 찾지 못했습니다 (건너뜀)")
                counts["error"] += 1
                continue
            clipdb.upsert_channel(conn, handle, title, ch.get("genre"))
            done = {
                r["id"]: r["segs"]
                for r in conn.execute(
                    "SELECT v.id, (SELECT COUNT(*) FROM segments s WHERE s.video_id = v.id) AS segs "
                    "FROM videos v WHERE v.status IN ('ok', 'no_captions') AND v.channel_handle = ?",
                    (handle,),
                )
            }
            pending = [i for i in ids if i not in done]
            details = {v["id"]: v for v in video_details(key, pending, handle)} if pending else {}
            for n, vid in enumerate(ids, 1):
                prefix = f"[{handle} {n}/{len(ids)}] {vid}"
                if vid in done:
                    counts["skipped"] += 1
                    print(f"{prefix} skip {done[vid]}")
                    continue
                meta = details.get(vid) or {"id": vid, "channel_handle": handle}
                try:
                    status, kind, segments = fetch_captions(ydl, vid, cache_dir, logger)
                    consecutive_errors = 0
                except (RateLimited, Blocked):
                    raise
                except Exception as e:
                    status, kind, segments = "error", None, []
                    consecutive_errors += 1
                    print(f"{prefix} error 0 ({str(e).splitlines()[0][:160] if str(e) else type(e).__name__})")
                    clipdb.save_video(conn, meta, status, kind, segments, datetime.now(timezone.utc).isoformat())
                    counts["error"] += 1
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        raise Blocked(f"연속 {MAX_CONSECUTIVE_ERRORS}편이 실패해 멈춥니다.")
                    time.sleep(args.video_sleep)
                    continue
                clipdb.save_video(conn, meta, status, kind, segments, datetime.now(timezone.utc).isoformat())
                counts[status] += 1
                counts["segments"] += len(segments)
                print(f"{prefix} {status} {len(segments)}" + (f" ({kind})" if kind else ""))
                time.sleep(args.video_sleep * random.uniform(0.8, 1.3))
    except RateLimited as e:
        print(f"\n중단: {e} 더 요청하지 않고 멈춥니다. 몇 시간 뒤 같은 명령을 다시 실행하면 이어받습니다.", file=sys.stderr)
        print_summary(counts, db)
        return EXIT_RATE_LIMITED
    except Blocked as e:
        print(f"\n중단: {e} 한동안 쉬었다가 다시 실행하세요 (이어받기 가능).", file=sys.stderr)
        print_summary(counts, db)
        return EXIT_BLOCKED
    except RuntimeError as e:
        print(f"\n중단: {e}", file=sys.stderr)
        print_summary(counts, db)
        return EXIT_FATAL
    finally:
        conn.close()
    print_summary(counts, db)
    return EXIT_OK


def print_summary(counts: Dict[str, int], db: Path) -> None:
    print(
        f"요약: ok={counts['ok']} no_captions={counts['no_captions']} error={counts['error']} "
        f"skipped={counts['skipped']} 새 세그먼트={counts['segments']} db={db}"
    )


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="유튜브 자막 DB 빌더(이어받기 가능)")
    p.add_argument("--channels", help="쉼표로 구분한 핸들(기본: 전체)")
    p.add_argument("--per-channel", type=int, default=300, help="채널마다 최근 영상 수(기본 300)")
    p.add_argument("--db", help="DB 경로(기본: CLIPDB_PATH 또는 기본 경로)")
    p.add_argument("--limit-videos", type=int, help="채널마다 이 수까지만 받는다(시험용)")
    p.add_argument("--request-sleep", type=float, default=1.5, help="yt-dlp 요청 사이 대기 초(최소 1)")
    p.add_argument("--subtitle-sleep", type=float, default=2.5, help="자막 다운로드 사이 대기 초(최소 2)")
    p.add_argument("--video-sleep", type=float, default=3.0, help="영상 사이 대기 초")
    args = p.parse_args(argv)
    args.request_sleep = max(1.0, args.request_sleep)
    args.subtitle_sleep = max(2.0, args.subtitle_sleep)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())

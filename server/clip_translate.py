"""POST /api/clips/translate: 클립 공부 화면의 한국어 줄(보는 줄만 번역하고 캐시한다).

- 번역은 줄마다 모델을 부르는 일이라 돈이 든다. 그래서 (1) 한 번 받은 줄은 캐시에서 꺼내 다시 부르지 않고,
  (2) 하루에 모델로 번역하는 줄 수에 상한(CLIP_TRANSLATE_DAILY_CAP, 기본 300)을 두며,
  (3) CLIP_TRANSLATE_ENABLED=0이면 아예 404로 닫는다.
- 캐시와 하루 사용량은 자막 DB 밖의 SQLite 파일이다(CLIP_TRANSLATE_CACHE_PATH, 기본은 자막 DB 옆
  `clip-translate-cache.sqlite`). 자막 DB는 건드리지 않는다.
- 캐시 키는 (영상, 줄 id, 줄 글의 sha1)이라 자막이 바뀌면 옛 번역이 나오지 않는다.
- 모델이 일부 줄만 돌려주거나 실패하면 그 줄은 응답에서 빠진다(캐시하지 않고 하루 사용량에도 넣지 않는다).
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
from datetime import date
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

from server import clipdb

logger = logging.getLogger(__name__)

router = APIRouter()

ENABLED_ENV = "CLIP_TRANSLATE_ENABLED"
CAP_ENV = "CLIP_TRANSLATE_DAILY_CAP"
CACHE_PATH_ENV = "CLIP_TRANSLATE_CACHE_PATH"
DEFAULT_DAILY_CAP = 300
MAX_LINES = 8
MAX_CONTEXT = 2
MAX_TEXT_CHARS = 300
MAX_KO_CHARS = 300
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,20}")

_LOCK = threading.Lock()

PROMPT = (
    "Translate each numbered English subtitle line from a video into natural spoken Korean for an English learner.\n"
    "Keep each translation short (one line, no explanation, no romanization). The lines are consecutive; use the "
    "context lines only to understand meaning and do not translate them.\n"
    'Return JSON only: {{"items": [{{"id": <id>, "ko": "<Korean translation>"}}]}} with exactly one item per line id.\n'
    "Context before: {before}\n"
    "Lines: {lines}\n"
    "Context after: {after}"
)


def enabled() -> bool:
    return os.getenv(ENABLED_ENV, "1").strip().lower() not in ("0", "false", "off", "no")


def daily_cap() -> int:
    try:
        return max(0, int(os.getenv(CAP_ENV, "").strip() or DEFAULT_DAILY_CAP))
    except ValueError:
        return DEFAULT_DAILY_CAP


def cache_path() -> Path:
    override = os.getenv(CACHE_PATH_ENV, "").strip()
    return Path(override).expanduser() if override else clipdb.db_path().with_name("clip-translate-cache.sqlite")


def _connect() -> sqlite3.Connection:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS translations ("
        "video_id TEXT NOT NULL, line_id INTEGER NOT NULL, text_hash TEXT NOT NULL, ko TEXT NOT NULL, "
        "PRIMARY KEY (video_id, line_id, text_hash))"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, lines INTEGER NOT NULL)")
    return conn


def _text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _today() -> str:
    return date.today().isoformat()


def _clean_text(value: Any) -> str:
    return " ".join(value.split())[:MAX_TEXT_CHARS] if isinstance(value, str) else ""


def parse_request(body: Any) -> Optional[dict]:
    """요청 본문을 정리한다. 형식이 틀리면 None."""
    if not isinstance(body, dict):
        return None
    video_id = body.get("video_id")
    raw_lines = body.get("lines")
    if not isinstance(video_id, str) or not VIDEO_ID_RE.fullmatch(video_id):
        return None
    if not isinstance(raw_lines, list) or not 1 <= len(raw_lines) <= MAX_LINES:
        return None
    lines: List[dict] = []
    for item in raw_lines:
        line_id = item.get("id") if isinstance(item, dict) else None
        text = _clean_text(item.get("text")) if isinstance(item, dict) else ""
        if isinstance(line_id, bool) or not isinstance(line_id, int) or not text:
            return None
        lines.append({"id": line_id, "text": text})
    if len({line["id"] for line in lines}) != len(lines):
        return None

    def context(key: str) -> List[str]:
        raw = body.get(key)
        texts = [_clean_text(t) for t in raw] if isinstance(raw, list) else []
        return [t for t in texts if t][:MAX_CONTEXT]

    return {"video_id": video_id, "lines": lines, "before": context("before"), "after": context("after")}


def _parse_items(raw: Any, wanted: List[int]) -> Dict[int, str]:
    """모델 응답에서 요청한 줄 id의 번역만 꺼낸다. 이상한 항목은 버린다."""
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    found: Dict[int, str] = {}
    for item in items if isinstance(items, list) else []:
        line_id = item.get("id") if isinstance(item, dict) else None
        ko = item.get("ko") if isinstance(item, dict) else None
        if isinstance(line_id, int) and not isinstance(line_id, bool) and line_id in wanted and isinstance(ko, str):
            ko = " ".join(ko.split())[:MAX_KO_CHARS]
            if ko:
                found[line_id] = ko
    return found


def translate_lines(req: dict, generate_text: Optional[Callable[[str], Any]] = None) -> dict:
    """캐시에 있는 줄은 그대로, 없는 줄은 하루 상한 안에서 모델로 번역한다.

    돌려주는 값: {"items": [{"id", "ko", "cached"}], "capped": 상한 때문에 빠진 줄이 있는가, "remaining": 오늘 남은 줄 수}.
    """
    video_id = req["video_id"]
    hashes = {line["id"]: _text_hash(line["text"]) for line in req["lines"]}
    items: List[dict] = []
    with _LOCK:
        conn = _connect()
        try:
            missing: List[dict] = []
            for line in req["lines"]:
                row = conn.execute(
                    "SELECT ko FROM translations WHERE video_id=? AND line_id=? AND text_hash=?",
                    (video_id, line["id"], hashes[line["id"]]),
                ).fetchone()
                if row:
                    items.append({"id": line["id"], "ko": row[0], "cached": True})
                else:
                    missing.append(line)
            day = _today()
            used_row = conn.execute("SELECT lines FROM usage WHERE day=?", (day,)).fetchone()
            used = used_row[0] if used_row else 0
            room = max(0, daily_cap() - used)
            send = missing[:room]
            capped = len(send) < len(missing)
            if send:
                if generate_text is None:
                    from server.tutor import make_generate_text

                    generate_text = make_generate_text()
                prompt = PROMPT.format(
                    before=json.dumps(req["before"], ensure_ascii=False),
                    lines=json.dumps(send, ensure_ascii=False),
                    after=json.dumps(req["after"], ensure_ascii=False),
                )
                try:
                    found = _parse_items(generate_text(prompt), [line["id"] for line in send])
                except Exception:
                    logger.warning("clip translate failed", exc_info=True)
                    found = {}
                for line in send:
                    ko = found.get(line["id"])
                    if ko is None:
                        continue
                    conn.execute(
                        "INSERT OR REPLACE INTO translations (video_id, line_id, text_hash, ko) VALUES (?, ?, ?, ?)",
                        (video_id, line["id"], hashes[line["id"]], ko),
                    )
                    items.append({"id": line["id"], "ko": ko, "cached": False})
                if found:
                    conn.execute(
                        "INSERT INTO usage (day, lines) VALUES (?, ?) ON CONFLICT(day) DO UPDATE SET lines = lines + excluded.lines",
                        (day, len(found)),
                    )
                    used += len(found)
                conn.commit()
        finally:
            conn.close()
    return {"items": items, "capped": capped, "remaining": max(0, daily_cap() - used)}


@router.post("/api/clips/translate")
async def clip_translate_endpoint(raw: Request):
    if not enabled():
        raise HTTPException(status_code=404, detail="한국어 줄 번역이 꺼져 있어요.")
    if "application/json" not in raw.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="JSON으로 보내야 합니다.")
    try:
        body = await raw.json()
    except Exception:
        body = None
    req = parse_request(body)
    if req is None:
        raise HTTPException(status_code=400, detail="요청 형식이 틀렸어요.")
    result = await asyncio.to_thread(translate_lines, req)
    if result["capped"] and not result["items"]:
        raise HTTPException(status_code=429, detail="오늘 번역 한도를 다 썼어요.")
    return result

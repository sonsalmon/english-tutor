"""유튜브 자막 DB(SQLite FTS5)에서 문구가 말해진 순간을 찾는다.

scripts/build_caption_db.py가 DB를 채우고, 서버는 search()로 읽는다.
VTT 정리·DB 쓰기 보조 함수도 여기 두어 빌더와 테스트가 같은 코드를 쓴다.
표준 라이브러리만 쓴다.
"""

import html
import logging
import os
import random
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from server.native_expr import lemma_tokens

logger = logging.getLogger(__name__)

# 채널 장르. 드라마·팟캐스트·직장(실제 말투)을 먼저 쓰고, 영어 강의 채널(daily)은 다른 장면이 없을 때만 쓴다.
LECTURE_GENRE = "daily"
TIER_PREFERRED = "preferred"
TIER_LECTURE = "lecture"
TIER_ALL = "all"


def in_tier(genre: Optional[str], tier: str) -> bool:
    """장르가 tier에 드는지. preferred=강의 채널이 아닌 것, lecture=강의 채널, all=전부."""
    if tier == TIER_ALL:
        return True
    return (genre == LECTURE_GENRE) == (tier == TIER_LECTURE)


def contains_phrase(text: str, phrase: str) -> bool:
    """자막 문장에 표현이 이어서 실제로 들어 있는지. 대소문자·문장부호는 무시하고 -s/-ed/-ing 정도의 어형 변화는 허용한다."""
    needle = lemma_tokens(phrase)
    hay = lemma_tokens(text)
    n = len(needle)
    return n > 0 and any(hay[i : i + n] == needle for i in range(len(hay) - n + 1))

DEFAULT_DB_PATH = Path.home() / "dev" / "learning" / "english" / "clipdb" / "captions.db"

# 세그먼트 병합 기준(초): 문장 끝이면 MIN_SENTENCE 이상, 아니면 SOFT_MAX 이상에서 끊고 HARD_MAX를 넘기지 않는다.
MIN_SENTENCE = 3.0
SOFT_MAX = 6.0
HARD_MAX = 8.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    handle TEXT PRIMARY KEY,
    title TEXT,
    genre TEXT
);
CREATE TABLE IF NOT EXISTS videos (
    id TEXT PRIMARY KEY,
    channel_handle TEXT NOT NULL,
    title TEXT,
    published TEXT,
    duration_sec INTEGER,
    caption_kind TEXT CHECK (caption_kind IN ('manual', 'auto')),
    status TEXT NOT NULL CHECK (status IN ('ok', 'no_captions', 'error')),
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS segments (
    video_id TEXT NOT NULL,
    start REAL NOT NULL,
    "end" REAL NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS segments_video ON segments(video_id, start);
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text, content='segments', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
END;
"""


def excerpt(text: str, phrase: str, max_words: int = 12, context: int = 2) -> str:
    """max_words낙말을 넘는 긴 자막은 화면에서 표현이 잘리지 않도록 표현과 앞뒤 context낙말만 남긴다(잘린 쪽은 …)."""
    words = str(text or "").split()
    if len(words) <= max_words:
        return " ".join(words)
    needle = lemma_tokens(phrase)
    flat = [(tok, i) for i, w in enumerate(words) for tok in lemma_tokens(w)]
    n = len(needle)
    for k in range(len(flat) - n + 1):
        if n and [t for t, _ in flat[k : k + n]] == needle:
            first, last = flat[k][1], flat[k + n - 1][1]
            lo, hi = max(0, first - context), min(len(words), last + 1 + context)
            return ("… " if lo else "") + " ".join(words[lo:hi]) + (" …" if hi < len(words) else "")
    return " ".join(words[:max_words])


def db_path() -> Path:
    """CLIPDB_PATH 환경변수가 있으면 그것을, 없으면 기본 경로를 쓴다."""
    env = os.environ.get("CLIPDB_PATH", "").strip()
    return Path(env).expanduser() if env else DEFAULT_DB_PATH


_CUE_RE = re.compile(
    r"((?:\d+:)?\d{1,2}:\d{2}\.\d{3})\s+-->\s+((?:\d+:)?\d{1,2}:\d{2}\.\d{3})"
)
_TAG_RE = re.compile(r"<[^>]*>")
_SOUND_RE = re.compile(r"\[[^\]]*\]|\([^)]*\)|♪+")
_SPACE_RE = re.compile(r"\s+")
_SENTENCE_END_RE = re.compile(r"[.?!][\"')\]]*$")


def _seconds(stamp: str) -> float:
    parts = stamp.split(":")
    h, m = (int(parts[0]), int(parts[1])) if len(parts) == 3 else (0, int(parts[0]))
    return h * 3600 + m * 60 + float(parts[-1])


def _clean(line: str) -> str:
    line = _TAG_RE.sub("", line)
    line = html.unescape(line)
    line = _SOUND_RE.sub(" ", line)
    line = line.replace(">>", " ")
    return _SPACE_RE.sub(" ", line).strip()


def _cues(vtt: str) -> List[Dict[str, Any]]:
    cues: List[Dict[str, Any]] = []
    for block in re.split(r"\n{2,}", vtt.replace("\r\n", "\n").replace("\r", "\n")):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = _CUE_RE.search(line)
            if m:
                cues.append(
                    {
                        "start": _seconds(m.group(1)),
                        "end": _seconds(m.group(2)),
                        "lines": [_clean(x) for x in lines[i + 1 :]],
                    }
                )
                break
    return cues


def _merge(units: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """짧은 단위(줄·큐)를 1~8초 안팎의 겹치지 않는 세그먼트로 묶는다."""
    segments: List[Dict[str, Any]] = []
    cur: Optional[Dict[str, Any]] = None
    for u in units:
        if cur is not None and u["end"] - cur["start"] > HARD_MAX:
            segments.append(cur)
            cur = None
        if cur is None:
            cur = {"start": u["start"], "end": u["end"], "text": u["text"]}
        else:
            cur["end"] = u["end"]
            cur["text"] = f'{cur["text"]} {u["text"]}'
        dur = cur["end"] - cur["start"]
        if dur >= SOFT_MAX or (dur >= MIN_SENTENCE and _SENTENCE_END_RE.search(cur["text"])):
            segments.append(cur)
            cur = None
    if cur is not None:
        segments.append(cur)
    for seg in segments:
        seg["start"] = round(seg["start"], 3)
        seg["end"] = round(max(seg["end"], seg["start"]), 3)
    return segments


def parse_vtt(vtt: str, rolling: Optional[bool] = None) -> List[Dict[str, Any]]:
    """VTT 문자열을 [{start, end, text}] 세그먼트로 바꾼다.

    rolling=True(자동 자막): 큐마다 직전 줄이 되풀이되므로 새 줄만 남긴다.
    rolling=False(수동 자막): 큐 하나를 한 단위로 본다. None이면 인라인 <c> 태그로 판별한다.
    """
    if rolling is None:
        rolling = "<c>" in vtt or re.search(r"<\d{2}:\d{2}[:.]", vtt) is not None
    cues = _cues(vtt)
    units: List[Dict[str, Any]] = []
    if rolling:
        prev_lines: set = set()
        for cue in cues:
            lines = [x for x in cue["lines"] if x]
            for text in lines:
                if text not in prev_lines:
                    units.append({"start": cue["start"], "end": cue["end"], "text": text})
            prev_lines = set(lines)
        # 줄이 말해진 시간은 다음 새 줄이 시작할 때까지다. 겹치지 않게 끝을 맞춘다.
        for cur, nxt in zip(units, units[1:]):
            if nxt["start"] - cur["start"] <= HARD_MAX:
                cur["end"] = max(cur["start"], nxt["start"])
    else:
        for cue in cues:
            text = _SPACE_RE.sub(" ", " ".join(x for x in cue["lines"] if x)).strip()
            if text:
                units.append({"start": cue["start"], "end": cue["end"], "text": text})
    for u in units:
        u["end"] = min(u["end"], u["start"] + HARD_MAX)
    return _merge(units)


def connect(path: Path) -> sqlite3.Connection:
    """쓰기용 연결. 폴더와 스키마가 없으면 만든다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def upsert_channel(conn: sqlite3.Connection, handle: str, title: Optional[str], genre: Optional[str]) -> None:
    conn.execute(
        "INSERT INTO channels(handle, title, genre) VALUES (?, ?, ?) "
        "ON CONFLICT(handle) DO UPDATE SET title = excluded.title, genre = excluded.genre",
        (handle, title, genre),
    )
    conn.commit()


def save_video(
    conn: sqlite3.Connection,
    video: Dict[str, Any],
    status: str,
    caption_kind: Optional[str],
    segments: List[Dict[str, Any]],
    fetched_at: str,
) -> None:
    """영상 한 편과 세그먼트를 한 트랜잭션으로 저장한다(다시 받으면 세그먼트를 교체한다)."""
    with conn:
        conn.execute("DELETE FROM segments WHERE video_id = ?", (video["id"],))
        conn.execute(
            "INSERT OR REPLACE INTO videos(id, channel_handle, title, published, duration_sec, "
            "caption_kind, status, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                video["id"],
                video["channel_handle"],
                video.get("title"),
                video.get("published"),
                video.get("duration_sec"),
                caption_kind,
                status,
                fetched_at,
            ),
        )
        conn.executemany(
            'INSERT INTO segments(video_id, start, "end", text) VALUES (?, ?, ?, ?)',
            [(video["id"], s["start"], s["end"], s["text"]) for s in segments],
        )


def _open_ro(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def available(path: Optional[Path] = None) -> bool:
    """DB가 있고 세그먼트가 하나라도 들어 있으면 True."""
    p = Path(path) if path else db_path()
    if not p.is_file():
        return False
    try:
        conn = _open_ro(p)
        try:
            return conn.execute("SELECT 1 FROM segments LIMIT 1").fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def random_segments(
    count: int,
    min_words: int = 6,
    max_words: int = 20,
    exclude_videos: Optional[set] = None,
    path: Optional[Path] = None,
    rng: Optional[random.Random] = None,
    tier: str = TIER_ALL,
) -> List[Dict[str, Any]]:
    """길이가 min_words~max_words인 문장 세그먼트를 무작위로 count개 뽑는다. 영상당 최대 1개, DB는 읽기 전용.

    전체 정렬(ORDER BY random())을 피해 rowid를 무작위로 고른 뒤 그 뒤의 첫 세그먼트를 읽는다(73만 행에서도 빠르다).
    tier=all이면 강의 채널이 아닌 장면을 먼저 뽑고 모자랄 때만 강의 채널(daily) 장면으로 채운다.
    """
    p = Path(path) if path else db_path()
    if count <= 0 or not p.is_file():
        return []
    rng = rng or random.Random()
    taken = set(exclude_videos or ())
    if tier == TIER_ALL:
        hits = random_segments(count, min_words, max_words, taken, p, rng, TIER_PREFERRED)
        taken |= {h["video_id"] for h in hits}
        return hits + random_segments(count - len(hits), min_words, max_words, taken, p, rng, TIER_LECTURE)
    sql = (
        'SELECT s.video_id, v.title AS title, c.title AS channel, c.genre AS genre, '
        's.start AS start, s."end" AS "end", s.text AS text '
        "FROM segments s JOIN videos v ON v.id = s.video_id "
        "LEFT JOIN channels c ON c.handle = v.channel_handle "
        "WHERE s.rowid >= ? AND v.status = 'ok' LIMIT 1"
    )
    hits: List[Dict[str, Any]] = []
    try:
        conn = _open_ro(p)
        try:
            top = conn.execute("SELECT MAX(rowid) FROM segments").fetchone()[0] or 0
            for _ in range(count * 40):
                if len(hits) >= count or top <= 0:
                    break
                row = conn.execute(sql, (rng.randint(1, top),)).fetchone()
                if row is None or row["video_id"] in taken or not in_tier(row["genre"], tier):
                    continue
                words = len(re.findall(r"[A-Za-z][A-Za-z'’-]*", row["text"]))
                if not min_words <= words <= max_words:
                    continue
                taken.add(row["video_id"])
                hits.append({k: row[k] for k in ("video_id", "title", "channel", "genre", "start", "end", "text")})
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("clipdb random failed: %s", e)
        return []
    return hits


def video_genres(video_ids: Iterable[str], path: Optional[Path] = None) -> Dict[str, Optional[str]]:
    """영상 id마다 채널 장르(모르면 None). DB가 없거나 읽지 못하면 빈 딕셔너리(호출한 쪽은 장르를 모르는 것으로 본다)."""
    ids = list(dict.fromkeys(v for v in video_ids if isinstance(v, str) and v))
    p = Path(path) if path else db_path()
    if not ids or not p.is_file():
        return {}
    out: Dict[str, Optional[str]] = {}
    try:
        conn = _open_ro(p)
        try:
            for start in range(0, len(ids), 500):
                chunk = ids[start : start + 500]
                rows = conn.execute(
                    "SELECT v.id AS id, c.genre AS genre FROM videos v "
                    "LEFT JOIN channels c ON c.handle = v.channel_handle "
                    f"WHERE v.id IN ({','.join('?' * len(chunk))})",
                    chunk,
                ).fetchall()
                out.update({r["id"]: r["genre"] for r in rows})
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("clipdb genres failed: %s", e)
        return {}
    return out


def _fts_phrase(phrase: str) -> str:
    return '"' + phrase.replace('"', '""') + '"'


def search(
    phrase: str,
    limit: int = 5,
    genre: Optional[str] = None,
    path: Optional[Path] = None,
    tier: str = TIER_ALL,
) -> List[Dict[str, Any]]:
    """문구를 말하는 순간을 bm25 순으로 찾는다. 영상당 최대 1건. DB가 없으면 [].

    자막 문장에 표현이 실제로 들어 있는 장면만 남긴다(FTS의 어간 일치로 딴 납말이 걸린 것은 버린다).
    tier=all이면 강의 채널이 아닌 장면을 먼저, 모자랄 때만 강의 채널(daily) 장면으로 채운다.
    """
    phrase = (phrase or "").strip()
    if limit <= 0 or not re.search(r"\w", phrase):
        return []
    p = Path(path) if path else db_path()
    if not p.is_file():
        return []
    sql = (
        'SELECT s.video_id, v.title AS title, c.title AS channel, c.genre AS genre, '
        's.start AS start, s."end" AS "end", s.text AS text, bm25(segments_fts) AS score '
        "FROM segments_fts "
        "JOIN segments s ON s.rowid = segments_fts.rowid "
        "JOIN videos v ON v.id = s.video_id "
        "LEFT JOIN channels c ON c.handle = v.channel_handle "
        "WHERE segments_fts MATCH ?"
    )
    params: List[Any] = [_fts_phrase(phrase)]
    if genre:
        sql += " AND c.genre = ?"
        params.append(genre)
    if tier == TIER_PREFERRED:
        sql += " AND (c.genre IS NULL OR c.genre != ?)"
        params.append(LECTURE_GENRE)
    elif tier == TIER_LECTURE:
        sql += " AND c.genre = ?"
        params.append(LECTURE_GENRE)
    sql += " ORDER BY score, s.rowid"
    if tier == TIER_ALL:
        first = search(phrase, limit, genre, p, TIER_PREFERRED)
        if len(first) >= limit:
            return first
        more = search(phrase, limit + len(first), genre, p, TIER_LECTURE)
        have = {h["video_id"] for h in first}
        return (first + [h for h in more if h["video_id"] not in have])[:limit]
    hits: List[Dict[str, Any]] = []
    seen: set = set()
    try:
        conn = _open_ro(p)
        try:
            for row in conn.execute(sql, params):
                if row["video_id"] in seen or not contains_phrase(row["text"], phrase):
                    continue
                seen.add(row["video_id"])
                hits.append(
                    {
                        "video_id": row["video_id"],
                        "title": row["title"],
                        "channel": row["channel"],
                        "genre": row["genre"],
                        "start": row["start"],
                        "end": row["end"],
                        "text": row["text"],
                    }
                )
                if len(hits) >= limit:
                    break
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("clipdb search failed: %s", e)
        return []
    return hits

"""한국-미국 문화 차이 DB(SQLite FTS5)에서 통화 주제에 맞는 항목을 찾는다.

scripts/build_culture_db.py가 DB를 채우고, 서버는 search()로 읽는다.
표준 라이브러리만 쓴다. DB가 없으면 빈 결과를 돌려준다.
"""

import json
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path.home() / "dev" / "learning" / "english" / "culturedb" / "culture.db"
ATTRIBUTION = "출처: BLEnD (CC BY-SA 4.0), CultureBank (MIT)"
MIN_AGREEMENT = 0.6

SCHEMA = """
CREATE TABLE blend (
    id TEXT PRIMARY KEY,
    en_question TEXT NOT NULL,
    kr_answers TEXT NOT NULL,
    us_answers TEXT NOT NULL
);
CREATE TABLE culturebank (
    rowid INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    country TEXT NOT NULL CHECK (country IN ('US', 'KR')),
    cultural_group TEXT,
    context TEXT,
    actor TEXT,
    actor_behavior TEXT,
    topic TEXT,
    agreement REAL,
    "desc" TEXT
);
CREATE VIRTUAL TABLE blend_fts USING fts5(
    en_question, content='blend', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE VIRTUAL TABLE culturebank_fts USING fts5(
    "desc", topic, context, content='culturebank', content_rowid='rowid',
    tokenize='porter unicode61'
);
"""


def db_path() -> Path:
    return Path(os.environ.get("CULTUREDB_PATH") or DEFAULT_DB_PATH)


def available() -> bool:
    return db_path().is_file()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path().resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _match(terms: List[str]) -> str:
    quoted = []
    for t in terms:
        t = (t or "").replace('"', " ").strip()
        if t:
            quoted.append(f'"{t}"')
    return " OR ".join(quoted)


def _loads(s: str) -> List[str]:
    try:
        v = json.loads(s)
        return [str(x) for x in v] if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


def search(terms: List[str], limit_blend: int = 3, limit_bank: int = 2) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {"blend": [], "bank": []}
    q = _match(terms)
    if not q or not available():
        return out
    try:
        conn = _connect()
    except sqlite3.Error:
        logger.exception("culturedb open failed")
        return out
    try:
        if limit_blend > 0:
            rows = conn.execute(
                "SELECT b.id, b.en_question, b.kr_answers, b.us_answers FROM blend_fts "
                "JOIN blend b ON b.rowid = blend_fts.rowid WHERE blend_fts MATCH ? "
                "ORDER BY bm25(blend_fts) LIMIT ?",
                (q, limit_blend),
            ).fetchall()
            out["blend"] = [
                {"id": r["id"], "question": r["en_question"],
                 "korea": _loads(r["kr_answers"]), "us": _loads(r["us_answers"])}
                for r in rows
            ]
        if limit_bank > 0:  # 국가별로 따로 뽑아 두 나라가 함께 보이게 한다(국가당 limit_bank건)
            rows = []
            for country in ("US", "KR"):
                rows += conn.execute(
                    "SELECT c.country, c.cultural_group, c.topic, c.context, c.\"desc\", c.agreement, c.source "
                    "FROM culturebank_fts JOIN culturebank c ON c.rowid = culturebank_fts.rowid "
                    "WHERE culturebank_fts MATCH ? AND c.country = ? AND (c.agreement IS NULL OR c.agreement >= ?) "
                    "ORDER BY bm25(culturebank_fts), c.agreement DESC LIMIT ?",
                    (q, country, MIN_AGREEMENT, limit_bank),
                ).fetchall()
            out["bank"] = [
                {"country": r["country"], "group": r["cultural_group"], "topic": r["topic"], "context": r["context"],
                 "text": r["desc"], "agreement": r["agreement"], "source": r["source"]}
                for r in rows
            ]
    except sqlite3.Error:
        logger.exception("culturedb search failed")
    finally:
        conn.close()
    return out

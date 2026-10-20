"""CultureBank와 BLEnD(한국·미국)를 받아 문화 차이 SQLite DB를 만든다.

임시 DB에 쓴 뒤 os.replace로 바꿔 넣으므로 다시 돌려도 안전하다.
"""

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
import culturedb  # noqa: E402

HF = "https://huggingface.co/datasets/{repo}/resolve/main/{path}"
SOURCES = {
    "reddit": ("SALT-NLP/CultureBank", "reddit/culturebank_reddit.csv"),
    "tiktok": ("SALT-NLP/CultureBank", "tiktok/culturebank_tiktok.csv"),
    "us": ("nayeon212/BLEnD", "data/annotations/US_data.json"),
    "kr": ("nayeon212/BLEnD", "data/annotations/South_Korea_data.json"),
}
US_EXACT = frozenset({
    "american", "americans", "americans in general", "us", "us citizens", "united states",
    "people in the us", "people in the united states", "the us", "usa",
})
KR_EXACT = frozenset({"korean", "koreans", "south korean", "south koreans", "people in south korea", "koreans in korea"})


def classify_group(group: str) -> Optional[str]:
    """허용 목록과 정확히 일치하는 집단만 분류한다. 나머지(소수 집단·비미국인·타국 거주자)는 제외."""
    g = " ".join(group.lower().split())
    if g in US_EXACT:
        return "US"
    if g in KR_EXACT:
        return "KR"
    return None


def fetch(key: str, cache: Path) -> Path:
    repo, path = SOURCES[key]
    dest = cache / f"{key}_{Path(path).name}"
    if not dest.exists():
        req = urllib.request.Request(HF.format(repo=repo, path=path), headers={"User-Agent": "culture-db-build"})
        with urllib.request.urlopen(req, timeout=120) as r, open(dest.with_suffix(dest.suffix + ".part"), "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        os.replace(dest.with_suffix(dest.suffix + ".part"), dest)
    return dest


def top_answers(entry: Dict[str, Any], field: str, n: int = 4) -> List[str]:
    anns = sorted(entry.get("annotations") or [], key=lambda a: -(a.get("count") or 0))
    out: List[str] = []
    for a in anns:
        v = a.get(field)
        items = v if isinstance(v, list) else [v]
        for x in items:
            x = str(x).strip() if x is not None else ""
            if x and x not in out:
                out.append(x)
                break
        if len(out) >= n:
            break
    return out


def blend_rows(kr: Dict[str, Any], us: Dict[str, Any]) -> List[tuple]:
    rows = []
    for qid in kr:
        if qid not in us:
            continue
        q = kr[qid].get("en_question") or us[qid].get("en_question")
        if not q:
            continue
        kr_ans = top_answers(kr[qid], "en_answers")
        us_ans = top_answers(us[qid], "en_answers")
        if not kr_ans or not us_ans:  # 한쪽 답이 비면 비교가 안 된다
            continue
        rows.append((
            qid, q,
            json.dumps(kr_ans, ensure_ascii=False),
            json.dumps(us_ans, ensure_ascii=False),
        ))
    return rows


def parse_agreement(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def bank_rows(csv_path: Path, source: str) -> List[tuple]:
    rows = []
    csv.field_size_limit(1 << 24)
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            group = (r.get("cultural group") or "").strip()
            country = classify_group(group)
            if country is None:
                continue
            desc = (r.get("eval_whole_desc") or "").strip()
            if not desc:
                continue
            rows.append((
                source, country, group, (r.get("context") or "").strip(), (r.get("actor") or "").strip(),
                (r.get("actor_behavior") or "").strip(), (r.get("topic") or "").strip(),
                parse_agreement(r.get("agreement")), desc,
            ))
    return rows


def write_db(db: Path, blend: List[tuple], bank: List[tuple]) -> None:
    conn = sqlite3.connect(db)
    try:
        conn.executescript(culturedb.SCHEMA)
        conn.executemany("INSERT INTO blend VALUES (?,?,?,?)", blend)
        conn.executemany(
            "INSERT INTO culturebank (source, country, cultural_group, context, actor, actor_behavior, topic, agreement, \"desc\") "
            "VALUES (?,?,?,?,?,?,?,?,?)", bank)
        conn.execute("INSERT INTO blend_fts(blend_fts) VALUES('rebuild')")
        conn.execute("INSERT INTO culturebank_fts(culturebank_fts) VALUES('rebuild')")
        conn.commit()
    finally:
        conn.close()


def build(db: Path) -> Dict[str, int]:
    db.parent.mkdir(parents=True, exist_ok=True)
    cache = db.parent / "cache"
    cache.mkdir(exist_ok=True)
    kr = json.loads(fetch("kr", cache).read_text(encoding="utf-8"))
    us = json.loads(fetch("us", cache).read_text(encoding="utf-8"))
    blend = blend_rows(kr, us)
    bank = bank_rows(fetch("reddit", cache), "reddit") + bank_rows(fetch("tiktok", cache), "tiktok")
    tmp = db.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    write_db(tmp, blend, bank)
    os.replace(tmp, db)
    return {"blend": len(blend), "culturebank": len(bank)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(culturedb.db_path()))
    args = ap.parse_args()
    print(build(Path(args.db)))


if __name__ == "__main__":
    main()

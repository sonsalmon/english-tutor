"""GET /api/feed: 영어 표현 클립 피드(릴스처럼 넘겨 보는 카드)에 쓸 자막 DB 장면.

- filter=mine: 내 표현(단어장 구, 최근 튜터링의 미국식 표현·기억할 단어. 이미 안다고 표시한 것은 뺀다)을 말하는 장면을
  표현마다 돌아가며 한 장씩 뽑고, 모자란 만큼은 무작위 장면으로 채운다.
- filter=browse: 무작위 장면만.
- filter=native: 원어민 표현 목록(native_expr)에서 표현마다 미리 붙여 둔 클립을 한 장씩. 알려 준 표현은 뺀다.
자막 DB(clipdb)는 읽기 전용으로만 연다. YouTube 검색 API는 쓰지 않아 비용이 없다.
"""

import asyncio
import json
import logging
import random
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

from fastapi import APIRouter

from server import clipdb, embeds, known, native_expr, readgloss
from server.transcript_store import get_tutoring_dir

logger = logging.getLogger(__name__)

router = APIRouter()

PAGE_DEFAULT = 6
PAGE_MAX = 12
SEEN_MAX = 400
ID_MAX = 40
TERMS_PER_PAGE = 12
PER_TERM = 3
TUTORING_FILES = 8
FILTERS = ("mine", "browse", "native")
OVERFETCH = 3
TAG_OVERFETCH = 24

Playable = Callable[[Iterable[str]], Set[str]]


def _keep(hits: List[Dict[str, Any]], playable: Optional[Playable]) -> List[Dict[str, Any]]:
    if playable is None:
        return hits
    ok = playable({h["video_id"] for h in hits})
    return [h for h in hits if h["video_id"] in ok]


def clip_id(hit: Dict[str, Any]) -> str:
    return f"{hit['video_id']}:{int(hit['start'])}"


def _tutoring_terms(directory: Optional[Path] = None) -> List[str]:
    folder = Path(directory) if directory else get_tutoring_dir()
    try:
        files = sorted((f for f in folder.glob("*.json") if not f.name.endswith(".review.json")), reverse=True)
    except OSError:
        return []
    terms: List[str] = []
    for path in files[:TUTORING_FILES]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for item in data.get("us_style") or []:
            if isinstance(item, dict):
                terms.append(str(item.get("natural") or ""))
        for item in data.get("vocab") or []:
            if isinstance(item, dict):
                terms.append(str(item.get("word") or ""))
    return terms


def collect_terms(phrases: List[str], tutoring_dir: Optional[Path] = None, known_path: Optional[Path] = None) -> List[str]:
    """내 표현 후보. 단어장 구가 먼저, 그다음 튜터링 표현. 같은 표현·이미 안다고 표시한 표현은 뺀다."""
    keys = known.keys_of(e["text"] for e in known.load(known_path))
    terms: List[str] = []
    seen: set = set()
    for raw in [*phrases, *_tutoring_terms(tutoring_dir)]:
        text = " ".join(str(raw or "").split())
        key = known.make_key(text)
        if len(key) < 2 or key in seen or known.is_known(text, keys):
            continue
        seen.add(key)
        terms.append(text)
    return terms


def _card(hit: Dict[str, Any], source: str, term: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": clip_id(hit),
        "video_id": hit["video_id"],
        "start": hit["start"],
        "end": hit["end"],
        "text": hit["text"],
        "title": hit.get("title") or "",
        "channel": hit.get("channel") or "",
        "source": source,
        "term": term,
        "match": native_expr.surface_match(hit["text"], native_expr.lemma_key(term)) if term else None,
    }


def native_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "expression": entry["expression"],
        "kind": entry["kind"],
        "meaning_ko": entry["meaning_ko"],
        "say_ko": entry.get("say_ko") or "",
        "why_hard": entry["why_hard"],
        "register": entry["register"],
        "example": entry["example"],
        "per_million": entry["per_million"],
    }


def build_native_page(
    entries: List[Dict[str, Any]],
    limit: int,
    seen: set,
    rng: Optional[random.Random] = None,
    known_path: Optional[Path] = None,
    learner_used: Optional[Set[Tuple[str, ...]]] = None,
    playable: Optional[Playable] = None,
    genres: Optional[Callable[[Iterable[str]], Dict[str, Optional[str]]]] = None,
) -> List[Dict[str, Any]]:
    """원어민 표현 카드 최대 limit장. 영어 강의 채널(daily) 장면은 쓰지 않는다(genres로 장르를 알 때).


    알려 준 표현과 학습자가 자기 통화에서 이미 쓴 표현(learner_used)은 뺀다. 중간 빈도 관용구·구동사를 앞에 두고 같은 단계 안에서는
    빈도에 비례해 섞는다. 표현마다 아직 안 본 클립 한 장, 같은 영상은 한 장만, 앱 안에서 틀 수 없는 영상(playable)은 내지 않는다.
    """
    rng = rng or random.Random()
    used = {s.split(":")[0] for s in seen}
    cards: List[Dict[str, Any]] = []
    pool = native_expr.eligible(entries, known_path)
    if learner_used:
        pool = native_expr.unused_by_learner(pool, learner_used)
    ordered = native_expr.native_order(pool, rng)
    window = max(1, limit) * OVERFETCH
    for start in range(0, len(ordered), window):
        chunk = ordered[start : start + window]
        ids = {c["video_id"] for e in chunk for c in e["clips"]}
        ok = playable(ids) if playable else None
        lecture = {v for v, g in genres(ids).items() if g == clipdb.LECTURE_GENRE} if genres else set()
        for entry in chunk:
            clip = next(
                (
                    c
                    for c in entry["clips"]
                    if clip_id(c) not in seen
                    and c["video_id"] not in used
                    and c["video_id"] not in lecture
                    and (ok is None or c["video_id"] in ok)
                ),
                None,
            )
            if clip is None:
                continue
            used.add(clip["video_id"])
            card = _card(clip, "native", entry["expression"])
            card["native"] = native_payload(entry)
            cards.append(card)
            if len(cards) >= limit:
                return cards
    return cards


def build_page(
    terms: List[str],
    mode: str,
    limit: int,
    seen: set,
    db_path: Optional[Path] = None,
    rng: Optional[random.Random] = None,
    playable: Optional[Playable] = None,
    entries: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """카드 최대 limit장. 본 장면(seen)과 같은 영상은 다시 내지 않는다.

    드라마·팟캐스트·직장 채널 장면을 먼저(내 표현 → 무작위), 영어 강의 채널(daily) 장면은 그래도 모자랄 때만(내 표현 → 무작위)
    채운다. playable이 있으면 앱 안에서 틀 수 없는 영상은 내지 않는다(단계마다 한 번에 묶어 확인).
    entries(원어민 표현 목록)가 있으면 무작위 장면에 그 장면이 담은 표현(tier 0 → 1, tier 2는 안 고른다)을 붙이고 표현이 붙은 장면을
    먼저 낸다(표현이 없는 장면은 붙은 장면이 모자랄 때만). 내 표현 카드는 표현이 목록과 같으면 같은 설명을 붙인다.
    """
    rng = rng or random.Random()
    cards: List[Dict[str, Any]] = []
    used = {s.split(":")[0] for s in seen}
    by_key = {e["key"]: e for e in entries or []}
    picked = rng.sample(terms, min(len(terms), TERMS_PER_PAGE)) if mode == "mine" and terms else []

    def mine(tier: str) -> None:
        depth = PER_TERM + 5
        found = {t: clipdb.search(t, depth, path=db_path, tier=tier) for t in picked}
        flat = [h for hits in found.values() for h in hits]
        ok = {h["video_id"] for h in _keep(flat, playable)}
        cursor = {term: 0 for term in picked}
        progressed = True
        while progressed and len(cards) < limit:
            progressed = False
            for term in picked:
                hits = found[term]
                while cursor[term] < len(hits):
                    hit = hits[cursor[term]]
                    cursor[term] += 1
                    if clip_id(hit) in seen or hit["video_id"] in used or hit["video_id"] not in ok:
                        continue
                    used.add(hit["video_id"])
                    card = _card(hit, "mine", term)
                    entry = by_key.get(native_expr.lemma_key(term))
                    if entry:
                        card["native"] = native_payload(entry)
                    cards.append(card)
                    progressed = True
                    break
                if len(cards) >= limit:
                    return

    def browse(tier: str) -> None:
        need = limit - len(cards)
        want = need * TAG_OVERFETCH if entries else need * OVERFETCH if playable else need
        tagged: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        plain: List[Tuple[Dict[str, Any], Optional[Dict[str, Any]]]] = []
        for hit in _keep(clipdb.random_segments(want, exclude_videos=used, path=db_path, rng=rng, tier=tier), playable):
            entry = native_expr.tag_expression(hit["text"], entries) if entries else None
            (tagged if entry else plain).append((hit, entry))
        for hit, entry in [*tagged, *plain]:
            if len(cards) >= limit:
                return
            if clip_id(hit) in seen or hit["video_id"] in used:
                continue
            used.add(hit["video_id"])
            if entry:
                card = _card(hit, "browse", entry["expression"])
                card["native"] = native_payload(entry)
            else:
                card = _card(hit, "browse")
            cards.append(card)

    for tier in (clipdb.TIER_PREFERRED, clipdb.TIER_LECTURE):
        if picked and len(cards) < limit:
            mine(tier)
        if len(cards) < limit:
            browse(tier)
    return cards[:limit]


def _saved_phrases() -> List[str]:
    snapshot = readgloss.bridge_snapshot()
    if snapshot is None:
        return []
    stored = [p for p in (snapshot[0].get("phrases") or {}).values() if isinstance(p, dict)]
    stored.sort(key=lambda p: p.get("ts") or 0, reverse=True)
    return [str(p.get("text") or "") for p in stored if 2 <= len(str(p.get("text") or "").split()) <= 8]


def _page(mode: str, limit: int, seen: set) -> Dict[str, Any]:
    if mode == "native":
        entries = native_expr.load()
        clips = build_native_page(entries, limit, seen, learner_used=native_expr.learner_ngrams(), playable=embeds.playable, genres=clipdb.video_genres)
        return {"available": True, "clips": clips, "terms": 0, "native": len(entries)}
    if not clipdb.available():
        return {"available": False, "clips": [], "terms": 0}
    terms = collect_terms(_saved_phrases()) if mode == "mine" else []
    entries = native_expr.eligible(native_expr.load())
    clips = build_page(terms, mode, limit, seen, playable=embeds.playable, entries=entries)
    return {"available": True, "clips": clips, "terms": len(terms)}


@router.get("/api/feed")
async def feed_endpoint(filter: str = "mine", limit: int = PAGE_DEFAULT, seen: str = ""):
    mode = filter if filter in FILTERS else "mine"
    size = max(1, min(PAGE_MAX, limit))
    seen_ids = {s.strip()[:ID_MAX] for s in seen.split(",") if s.strip()}
    if len(seen_ids) > SEEN_MAX:
        seen_ids = set(list(seen_ids)[:SEEN_MAX])
    return await asyncio.to_thread(_page, mode, size, seen_ids)

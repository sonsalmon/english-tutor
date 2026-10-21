"""요약 검토 API: 항목별 저장·이미 알아요·인식 오류 표시, 검토가 끝난 뒤의 카드 갱신, 예시 클립.

표시 상태는 통화별로 `tutoring/<stem>.review.json`(`{"items": {"<kind>:<key>": state}}`)에 두고,
`known`·`misheard`는 `known.py` 저장소에도 넣어 다시 제안되지 않게 한다. 학습자 카드 갱신은 `/api/tutor`가
바로 걸지 않고 여기서 모아 두었다가 검토가 끝나거나(`finish`) 15분이 지나면 한 번만 건다.
"""

import asyncio
import json
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

from server import clipdb, embeds, known
from server.tutor import resolve_transcript
from server.transcript_store import get_tutoring_dir

logger = logging.getLogger(__name__)

router = APIRouter()

KINDS = ("correction", "us_style", "vocab", "good")
STATES = ("saved", "known", "misheard")
FLAGGED_STATES = ("known", "misheard")
STEM_RE = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}", re.ASCII)
MAX_TEXT = 300
MAX_PHRASE_QUERY = 80
DEFAULT_PHRASE_CLIPS = 3
MAX_PHRASE_CLIPS = 5
PHRASE_OVERFETCH = 4

CARD_DELAY_SEC = 15 * 60

_LOCK = threading.Lock()
_PENDING: Dict[str, dict] = {}
_TIMERS: "Dict[str, asyncio.Task]" = {}
_update_card: Optional[Callable[[str, dict], None]] = None


def configure(update_card: Callable[[str, dict], None]) -> None:
    """검토가 끝났을 때 카드 갱신을 거는 함수를 등록한다(main이 시작할 때 한 번)."""
    global _update_card
    _update_card = update_card


def review_path(stem: str) -> Path:
    return get_tutoring_dir() / f"{stem}.review.json"


def item_key(kind: str, text: str) -> str:
    return f"{kind}:{known.make_key(text)}"


def load_items(stem: str) -> Dict[str, str]:
    try:
        data = json.loads(review_path(stem).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        logger.error("검토 표시 파일을 읽지 못했습니다 %s: %s", stem, e)
        return {}
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, dict):
        return {}
    return {k: v for k, v in items.items() if isinstance(k, str) and v in STATES}


def _save_items(stem: str, items: Dict[str, str]) -> None:
    path = review_path(stem)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def apply_flag(stem: str, kind: str, text: str, state: Optional[str]) -> None:
    """항목 하나의 표시를 바꾼다. state가 None이면 되돌린다(알려 준 표현 저장소에서도 지운다)."""
    key = item_key(kind, text)
    with _LOCK:
        items = load_items(stem)
        previous = items.get(key)
        if state is None:
            items.pop(key, None)
        else:
            items[key] = state
        if previous in FLAGGED_STATES and state != previous:
            known.remove(text)
        if state in FLAGGED_STATES:
            known.add(text, state, stem)
        _save_items(stem, items)


def filter_tutoring(stem: str, tutoring: dict) -> dict:
    """카드 갱신에 넘길 튜터링에서 사용자가 이미 안다고 하거나 인식 오류라고 표시한 corrections·us_style를 뺀다."""
    items = load_items(stem)
    if not items:
        return tutoring

    def keep(kind: str, field: str):
        return lambda row: items.get(item_key(kind, str((row or {}).get(field, "")))) not in FLAGGED_STATES

    out = dict(tutoring)
    out["corrections"] = [r for r in tutoring.get("corrections") or [] if keep("correction", "better")(r)]
    out["us_style"] = [r for r in tutoring.get("us_style") or [] if keep("us_style", "natural")(r)]
    return out


def _flush(stem: str) -> bool:
    tutoring = _PENDING.pop(stem, None)
    if tutoring is None or _update_card is None:
        return False
    _update_card(stem, filter_tutoring(stem, tutoring))
    return True


async def _timer(stem: str) -> None:
    try:
        await asyncio.sleep(CARD_DELAY_SEC)
        _flush(stem)
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 - 카드 갱신은 부가 기능
        logger.error("지연된 카드 갱신 실패 %s: %s", stem, e)
    finally:
        _TIMERS.pop(stem, None)


def defer_card_update(stem: str, tutoring: dict) -> None:
    """이 통화의 카드 갱신 재료를 보관하고 15분 타이머를 건다(통화당 한 번, 이미 있으면 그대로)."""
    if stem in _PENDING:
        return
    _PENDING[stem] = tutoring
    _TIMERS[stem] = asyncio.get_running_loop().create_task(_timer(stem))


def finish(stem: str) -> bool:
    """검토가 끝났다는 신호. 보관 중인 카드 갱신이 있으면 지금 걸고 True."""
    timer = _TIMERS.pop(stem, None)
    if timer is not None:
        timer.cancel()
    return _flush(stem)


async def _json_object(raw: Request) -> dict:
    if "application/json" not in raw.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="JSON으로 보내야 합니다.")
    try:
        body = await raw.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="요청 형식이 틀렸어요.")
    return body


def _valid_stem(stem: Any) -> str:
    if not isinstance(stem, str) or not STEM_RE.fullmatch(stem):
        raise HTTPException(status_code=400, detail="통화 기록 이름이 틀렸어요.")
    return stem


@router.post("/api/review/flag")
async def flag_endpoint(raw: Request):
    """항목 하나를 saved·known·misheard로 표시하고, state가 null이면 되돌린다. 형식이 틀리면 400, 통화가 없으면 404."""
    body = await _json_object(raw)
    stem = _valid_stem(body.get("stem"))
    kind, text, state = body.get("kind"), body.get("text"), body.get("state")
    if kind not in KINDS or "state" not in body or (state is not None and state not in STATES):
        raise HTTPException(status_code=400, detail="kind나 state가 틀렸어요.")
    text = " ".join(text.split()) if isinstance(text, str) else ""
    if not text or len(text) > MAX_TEXT or not known.make_key(text):
        raise HTTPException(status_code=400, detail="표현이 비었거나 너무 길어요.")
    try:
        await asyncio.to_thread(resolve_transcript, f"{stem}.md")
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    await asyncio.to_thread(apply_flag, stem, kind, text, state)
    return {"status": "ok", "state": state}


@router.get("/api/calls/{stem}/review")
async def review_endpoint(stem: str):
    """이 통화에서 표시한 항목들(`{"<kind>:<key>": state}`). 표시가 없으면 빈 객체."""
    stem = _valid_stem(stem)
    return {"items": await asyncio.to_thread(load_items, stem)}


@router.post("/api/calls/{stem}/review/finish")
async def finish_endpoint(stem: str, raw: Request):
    """요약 검토를 마쳤다는 신호(JSON 본문 {} 필수). 기다리던 카드 갱신이 있으면 scheduled, 없으면 nothing."""
    stem = _valid_stem(stem)
    await _json_object(raw)
    return {"status": "scheduled" if finish(stem) else "nothing"}


def _phrase_hits(query: str, limit: int) -> list:
    """표현이 자막에 실제로 들어 있고 앱 안에서 틀 수 있는 장면. 드라마·팟캐스트·직장 채널이 먼저이고 강의 채널은 그게 하나도 없을 때만."""
    for tier in (clipdb.TIER_PREFERRED, clipdb.TIER_LECTURE):
        hits = clipdb.search(query, limit=limit * PHRASE_OVERFETCH, tier=tier)
        ok = embeds.playable({h["video_id"] for h in hits if h.get("video_id")})
        hits = [h for h in hits if h.get("video_id") in ok][:limit]
        if hits:
            return hits
    return []


@router.post("/api/clips/blocked")
async def blocked_clip_endpoint(raw: Request):
    """클라이언트 플레이어가 재생 오류를 낸 영상 id({"video_id": ...})를 받아 다음부터 피드·예시 클립에서 뺀다. id 모양이 틀리면 400."""
    body = await _json_object(raw)
    if not await asyncio.to_thread(embeds.mark_blocked, body.get("video_id")):
        raise HTTPException(status_code=400, detail="영상 id가 틀렸어요.")
    return {"status": "ok"}


@router.get("/api/clips/phrase")
async def phrase_clips_endpoint(q: str = "", limit: int = DEFAULT_PHRASE_CLIPS):
    """표현을 말하는 순간을 자막 DB에서 찾는다. 표현이 이상하면 no_query, DB가 없으면 no_db(둘 다 200)."""
    query = " ".join(q.split())
    if not 2 <= len(query) <= MAX_PHRASE_QUERY or not known.make_key(query):
        return {"status": "no_query", "query": "", "clips": []}
    if not clipdb.available():
        return {"status": "no_db", "query": query, "clips": []}
    hits = await asyncio.to_thread(_phrase_hits, query, max(1, min(limit, MAX_PHRASE_CLIPS)))
    clips = [
        {
            "id": h["video_id"],
            "title": h.get("title") or "",
            "channel": h.get("channel") or "",
            "thumbnail": f"https://i.ytimg.com/vi/{h['video_id']}/mqdefault.jpg",
            "start": int(h.get("start") or 0),
            "text": clipdb.excerpt(h.get("text") or "", query),
            "phrase": query,
            "source": "db",
        }
        for h in hits
        if h.get("video_id")
    ]
    return {"status": "ok", "query": query, "clips": clips}

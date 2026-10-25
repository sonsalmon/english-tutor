"""GET /api/wordbook: 단어장 탭이 보여 줄 readgloss의 단어와 저장한 문장(구 카드).

목록은 읽기 전용이다. 읽던 문장(sentence)과 페이지 주소(url)는 목록에 내지 않는다.
삭제·되돌리기는 readgloss 다리의 unsave·unsave-phrase·save 연산을 그대로 써서, 새로고침해도 지운 채로 남는다.
다리(readgloss)가 꺼져 있으면 503이다(다른 readgloss 엔드포인트와 같다).
"""

import asyncio
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from server import readgloss

router = APIRouter()

READGLOSS_OFF_DETAIL = "readgloss가 꺼져 있어 단어장을 불러오지 못했어요."
WORD_LIMIT = 500
PHRASE_LIMIT = 500
TEXT_MAX = 300


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_wordbook(state: dict, review: Optional[dict]) -> Dict[str, List[Dict[str, Any]]]:
    """readgloss 상태를 화면용으로 줄인다. 단어는 저장한 순서의 최신순.

    status: "due"(오늘 복습할 차례), "done"(복습을 마침), "learning"(그 밖).
    """
    due = {
        str(i.get("key")).lower()
        for i in (review or {}).get("due") or []
        if isinstance(i, dict) and i.get("type") == "word" and i.get("key")
    }
    words: List[Dict[str, Any]] = []
    saved = [(k, v) for k, v in (state.get("saved") or {}).items() if isinstance(v, dict)]
    for lemma, v in sorted(saved, key=lambda kv: kv[1].get("ts") or 0, reverse=True):
        key = str(lemma).lower()
        status = "done" if (v.get("review") or {}).get("done") else "due" if key in due else "learning"
        words.append(
            {
                "lemma": key,
                "word": _text(v.get("word") or lemma, 64),
                "gloss": _text(v.get("gloss"), readgloss.SAVE_GLOSS_MAX),
                "ts": int(v.get("ts") or 0),
                "status": status,
            }
        )
        if len(words) >= WORD_LIMIT:
            break
    phrases: List[Dict[str, Any]] = []
    stored = [(k, v) for k, v in (state.get("phrases") or {}).items() if isinstance(v, dict)]
    for pid, v in sorted(stored, key=lambda kv: kv[1].get("ts") or 0, reverse=True):
        text = _text(v.get("text"), TEXT_MAX)
        if not text:
            continue
        phrases.append({"id": str(pid), "text": text, "gloss": _text(v.get("translation"), TEXT_MAX), "ts": int(v.get("ts") or 0)})
        if len(phrases) >= PHRASE_LIMIT:
            break
    return {"words": words, "phrases": phrases}


@router.get("/api/wordbook")
async def wordbook_endpoint():
    snapshot = await asyncio.to_thread(readgloss.bridge_snapshot)
    if snapshot is None:
        raise HTTPException(status_code=503, detail=READGLOSS_OFF_DETAIL)
    return build_wordbook(snapshot[0], snapshot[1])


PHRASE_ID_RE = re.compile(r"[0-9a-f]{12}")
DELETE_OFF_DETAIL = "readgloss가 꺼져 있어 지우지 못했어요."
RESTORE_OFF_DETAIL = "readgloss가 꺼져 있어 되돌리지 못했어요."
NOT_FOUND_DETAIL = "이미 없는 항목이에요."
BAD_ID_DETAIL = "항목 이름이 올바르지 않아요."
BAD_RESTORE_DETAIL = "되돌릴 내용이 올바르지 않아요."


def _snapshot(kind: str, key: str, entry: dict) -> Dict[str, Any]:
    """지우기 전 항목 전체. 되돌리기에 그대로 돌려받는다(읽던 문장·주소 포함, 이 화면 밖으로는 안 나간다)."""
    snap = {k: v for k, v in entry.items() if k in _KEEP[kind] and v not in (None, "")}
    snap["type"] = kind
    snap["key" if kind == "word" else "id"] = key
    return snap


_KEEP = {
    "word": ("word", "gloss", "sentence", "url", "headings", "memo"),
    "phrase": ("text", "translation", "kind", "sentence", "url", "title", "context", "headings", "memo"),
}


def delete_item(kind: str, key: str) -> Dict[str, Any]:
    """저장소(readgloss 다리)에서 단어나 구를 지운다. 되돌릴 수 있게 지우기 전 내용을 돌려준다."""
    if kind == "word":
        key = key.lower()
        if not readgloss.LEMMA_RE.fullmatch(key):
            raise HTTPException(status_code=400, detail=BAD_ID_DETAIL)
        group, op = "saved", {"op": "unsave", "lemma": key}
    else:
        if not PHRASE_ID_RE.fullmatch(key):
            raise HTTPException(status_code=400, detail=BAD_ID_DETAIL)
        group, op = "phrases", {"op": "unsave-phrase", "id": key}
    state = readgloss._request("GET", "/words")
    if not isinstance(state, dict):
        raise HTTPException(status_code=503, detail=DELETE_OFF_DETAIL)
    entry = (state.get(group) or {}).get(key)
    if not isinstance(entry, dict):
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    if readgloss._request("POST", "/words", op) is None:
        raise HTTPException(status_code=503, detail=DELETE_OFF_DETAIL)
    return _snapshot(kind, key, entry)


def restore_item(snap: Dict[str, Any]) -> Dict[str, Any]:
    """지운 항목을 다시 저장한다. 메모는 살리고, 복습 진행도는 새로 시작한다."""
    kind = snap.get("type")
    if kind == "word":
        key = str(snap.get("key") or "").lower()
        if not readgloss.LEMMA_RE.fullmatch(key):
            raise HTTPException(status_code=400, detail=BAD_RESTORE_DETAIL)
        op: Dict[str, Any] = {
            "op": "save",
            "lemma": key,
            "word": str(snap.get("word") or key),
            "gloss": str(snap.get("gloss") or ""),
            "sentence": str(snap.get("sentence") or ""),
            "url": str(snap.get("url") or ""),
        }
        memo_target: Dict[str, Any] = {"lemma": key}
    elif kind == "phrase":
        text = str(snap.get("text") or "")
        if not text.strip():
            raise HTTPException(status_code=400, detail=BAD_RESTORE_DETAIL)
        op = {
            "op": "save-phrase",
            "text": text,
            "translation": str(snap.get("translation") or ""),
            "kind": snap.get("kind") if snap.get("kind") in ("expression", "sentence") else "expression",
            "title": str(snap.get("title") or ""),
            "sentence": str(snap.get("sentence") or ""),
            "url": str(snap.get("url") or ""),
        }
        if isinstance(snap.get("context"), dict):
            op["context"] = snap["context"]
        memo_target = {"id": str(snap.get("id") or "")}
    else:
        raise HTTPException(status_code=400, detail=BAD_RESTORE_DETAIL)
    if isinstance(snap.get("headings"), list):
        op["headings"] = snap["headings"]
    if readgloss._request("POST", "/words", op) is None:
        # 다리가 꺼진 것인지 값이 거절된 것인지 구분하려고 살아 있는지 한 번 본다.
        if readgloss._request("GET", "/ping") is None:
            raise HTTPException(status_code=503, detail=RESTORE_OFF_DETAIL)
        raise HTTPException(status_code=400, detail=BAD_RESTORE_DETAIL)
    memo = str(snap.get("memo") or "")
    if memo and memo_target.get("id", "x"):
        readgloss._request("POST", "/words", {"op": "memo", "memo": memo, **memo_target})
    return {"ok": True}


class RestoreBody(BaseModel):
    snapshot: Dict[str, Any]


@router.delete("/api/wordbook/{kind}/{key}")
async def delete_endpoint(kind: str, key: str):
    if kind not in ("word", "phrase"):
        raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)
    snapshot = await asyncio.to_thread(delete_item, kind, key)
    return {"ok": True, "snapshot": snapshot}


@router.post("/api/wordbook/restore")
async def restore_endpoint(body: RestoreBody):
    return await asyncio.to_thread(restore_item, body.snapshot)

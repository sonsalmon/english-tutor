"""GET /api/wordbook: 단어장 탭이 보여 줄 readgloss의 단어와 저장한 문장(구 카드).

읽기 전용이다. 읽던 문장(sentence)과 페이지 주소(url)는 화면에도 내지 않는다.
다리(readgloss)가 꺼져 있으면 503이다(다른 readgloss 엔드포인트와 같다).
"""

import asyncio
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

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

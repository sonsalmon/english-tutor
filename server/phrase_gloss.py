"""POST /api/phrase/gloss: 영어 구(두 낱말 이상)의 짧은 한국어 뜻 한 줄.

구 카드를 저장할 때 뜻이 비어 있으면 화면이 이 주소로 묻는다. 모델 호출이 실패해도
오류를 내지 않고 빈 뜻을 돌려줘서, 화면이 뜻 없이도 저장할 수 있게 한다.
"""

import asyncio
import json
import logging
import threading
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter()

MIN_CHARS = 2
MAX_CHARS = 80
MAX_GLOSS_CHARS = 60
CACHE_LIMIT = 500

# 같은 프로세스 안에서 한 번 받은 뜻은 다시 묻지 않는다. 실패(빈 뜻)는 담지 않아 다시 누르면 재시도한다.
_CACHE: Dict[str, str] = {}
_CACHE_LOCK = threading.Lock()

PROMPT = (
    "Give a short Korean meaning for this English phrase, as a dictionary would: at most 25 Korean characters, "
    "no quotes, no romanization, no explanation.\n"
    'Return JSON only: {{"gloss": "<Korean meaning>"}}\n'
    "Phrase: {phrase}"
)


def normalize(text: Any) -> str:
    """공백을 하나로 줄이고 앞뒤를 자른다. 형식이 틀리면 빈 문자열."""
    return " ".join(text.split()) if isinstance(text, str) else ""


def valid_phrase(text: str) -> bool:
    return MIN_CHARS <= len(text) <= MAX_CHARS and any(ch.isalpha() for ch in text)


def _cache_key(text: str) -> str:
    return text.lower()


def _parse_gloss(raw: Any) -> str:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return ""
    gloss = data.get("gloss") if isinstance(data, dict) else None
    return " ".join(gloss.split())[:MAX_GLOSS_CHARS] if isinstance(gloss, str) else ""


def gloss_phrase(text: str, generate_text: Optional[Callable[[str], Any]] = None) -> str:
    """구의 한국어 뜻. 모델이 실패하면 빈 문자열(이 경우 캐시하지 않는다)."""
    key = _cache_key(text)
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    try:
        if generate_text is None:
            from server.tutor import make_generate_text

            generate_text = make_generate_text()
        gloss = _parse_gloss(generate_text(PROMPT.format(phrase=json.dumps(text, ensure_ascii=False))))
    except Exception:
        logger.warning("phrase gloss failed", exc_info=True)
        return ""
    if gloss:
        with _CACHE_LOCK:
            if len(_CACHE) >= CACHE_LIMIT:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = gloss
    return gloss


@router.post("/api/phrase/gloss")
async def phrase_gloss_endpoint(raw: Request):
    if "application/json" not in raw.headers.get("content-type", ""):
        raise HTTPException(status_code=415, detail="JSON으로 보내야 합니다.")
    try:
        body = await raw.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="요청 형식이 틀렸어요.")
    text = normalize(body.get("text"))
    if not valid_phrase(text):
        raise HTTPException(status_code=400, detail="표현은 글자가 있는 2자 이상 80자 이하여야 해요.")
    return {"gloss": await asyncio.to_thread(gloss_phrase, text)}

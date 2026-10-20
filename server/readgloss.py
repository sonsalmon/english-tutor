"""readgloss(영어 읽기 확장)의 다리 서버와 단어를 주고받는다.

- 읽기: 최근 찾아본 단어·복습할 단어·단어장 단어 몇 개를 골라 통화에서 써 보게 한다.
- 쓰기: 통화 튜터링의 새 단어·고친 표현을 readgloss 단어장(복습 고리)에 넣는다.

다리가 꺼져 있거나 토큰이 없으면 조용히 건너뛴다(통화 앱은 readgloss 없이도 돈다).
Google로 가는 통화 지시문에는 단어와 뜻만 넘기고, 읽던 문장·페이지 주소는 넘기지 않는다.
"""

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

URL_ENV = "READGLOSS_URL"
TOKEN_FILE_ENV = "READGLOSS_TOKEN_FILE"
DEFAULT_URL = "http://127.0.0.1:47831"
DEFAULT_TOKEN_FILE = "~/dev/readgloss/data/token"
# 다리는 DNS 리바인딩을 막으려고 Host 머리글이 이 값인지 검사한다. 시험 다리를 다른 포트에 띄워도 같은 값을 보낸다.
BRIDGE_HOST = "127.0.0.1:47831"
TIMEOUT_SEC = 2.0

PRACTICE_LIMIT = 5
# 복습할 단어가 수십 개 밀려 있으면 최근 찾아본 단어가 안 보여서, 복습은 먼저 최대 3개만 넣고 남은 자리를 나중에 채운다.
REVIEW_FIRST = 3
LOOKUP_DAYS = 14
GLOSS_MAX = 40
PUSH_LIMIT = 5
# readgloss bridge/lookup.mjs WORD_RE와 같은 규칙(원형 키).
WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’-]{0,63}")
LEMMA_RE = re.compile(r"[a-z][a-z'’-]{1,63}")


def _token() -> Optional[str]:
    path = os.path.expanduser(os.environ.get(TOKEN_FILE_ENV) or DEFAULT_TOKEN_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            token = f.read().strip()
    except OSError:
        return None
    return token or None


def _request(method: str, path: str, body: Optional[dict] = None) -> Optional[Any]:
    """다리 요청 한 번. 실패하면 None(다리 꺼짐·토큰 없음·거절·깨진 응답)."""
    token = _token()
    if not token:
        return None
    url = (os.environ.get(URL_ENV) or DEFAULT_URL).rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Bridge-Token", token)
    req.add_header("Host", BRIDGE_HOST)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
            return json.loads(res.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as e:
        logger.info("readgloss bridge %s %s skipped: %s", method, path, e)
        return None


def _gloss(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text[:GLOSS_MAX]


def pick_practice_words(state: dict, review: Optional[dict], now: datetime, limit: int = PRACTICE_LIMIT) -> List[Dict[str, str]]:
    """복습할 단어(최대 3) → 최근 찾아본 단어(14일) → 단어장 최근 → 남은 복습 단어 순으로 원형을 고른다. 아는 단어는 뺀다."""
    known = set((state.get("known") or {}).keys())
    picked: Dict[str, Dict[str, str]] = {}

    def add(lemma: Any, gloss: Any, source: str) -> None:
        if len(picked) >= limit or not isinstance(lemma, str):
            return
        key = lemma.lower()
        if key in picked or key in known or not LEMMA_RE.fullmatch(key):
            return
        picked[key] = {"lemma": key, "gloss": _gloss(gloss), "source": source}

    due = [i for i in (review or {}).get("due") or [] if isinstance(i, dict) and i.get("type") == "word"]
    for item in due[:REVIEW_FIRST]:
        add(item.get("key"), item.get("gloss"), "review")

    cutoff_ms = (now - timedelta(days=LOOKUP_DAYS)).timestamp() * 1000
    history = [h for h in state.get("history") or [] if isinstance(h, dict)]
    for h in sorted(history, key=lambda h: h.get("ts") or 0, reverse=True):
        if (h.get("ts") or 0) >= cutoff_ms:
            add(h.get("lemma"), h.get("gloss"), "lookup")

    saved = [(k, v) for k, v in (state.get("saved") or {}).items() if isinstance(v, dict)]
    for lemma, v in sorted(saved, key=lambda kv: kv[1].get("ts") or 0, reverse=True):
        if not (v.get("review") or {}).get("done"):
            add(lemma, v.get("gloss"), "saved")

    for item in due[REVIEW_FIRST:]:
        add(item.get("key"), item.get("gloss"), "review")

    return list(picked.values())


def practice_words(now: Optional[datetime] = None) -> List[Dict[str, str]]:
    """다리에서 오늘 통화에 써 볼 단어를 고른다. 다리가 없으면 []."""
    state = _request("GET", "/words")
    if not isinstance(state, dict):
        return []
    review = _request("GET", "/words/review")
    return pick_practice_words(state, review if isinstance(review, dict) else None, now or datetime.now())


def _forms(lemma: str) -> set:
    forms = {lemma, lemma + "s", lemma + "es", lemma + "ed", lemma + "d", lemma + "ing"}
    if lemma.endswith("e"):
        forms.add(lemma[:-1] + "ing")
    if lemma.endswith("y"):
        forms |= {lemma[:-1] + "ies", lemma[:-1] + "ied"}
    return forms


def words_used(transcript: str, lemmas: Iterable[str], verbatim: str = "") -> List[str]:
    """전문의 학습자 줄(**Me:**)과 원음 받아쓰기에서 원형이나 흔한 굴절형(-s·-ed·-ing 등)으로 쓴 단어.

    실시간 자막은 학습자 말을 놓칠 때가 있어 원음 받아쓰기(마이크 소리만)도 함께 본다.
    """
    me_lines = (line[len("**Me:**"):] for line in transcript.splitlines() if line.startswith("**Me:**"))
    spoken = (" ".join(me_lines) + " " + verbatim).lower()
    tokens = set(re.findall(r"[a-z][a-z'’-]*", spoken))
    return [lemma for lemma in lemmas if _forms(lemma) & tokens]


def push_ops(tutoring: dict, title: str) -> List[dict]:
    """튜터링 결과 → readgloss /words 요청들. 한 낱말 단어는 단어장, 여러 낱말·고친 표현은 구 항목."""
    ops: List[dict] = []
    for v in (tutoring.get("vocab") or [])[:PUSH_LIMIT]:
        word = " ".join(str((v or {}).get("word") or "").split())
        meaning = str((v or {}).get("meaning_ko") or "")[:200]
        if not word:
            continue
        if WORD_RE.fullmatch(word):
            ops.append({"op": "save", "lemma": word.lower(), "word": word, "gloss": meaning, "sentence": "", "url": ""})
        else:
            ops.append({"op": "save-phrase", "text": word[:1000], "translation": meaning, "kind": "expression", "title": title, "sentence": "", "url": ""})
    for c in (tutoring.get("corrections") or [])[:PUSH_LIMIT]:
        better = " ".join(str((c or {}).get("better") or "").split())
        # 한 낱말 교정(발음·시제 "Ms."·"mitigated")은 문맥 없이 복습 카드가 되면 쓸모가 없어 두 낱말 이상만 넣는다.
        if len(better.split()) >= 2:
            why = str((c or {}).get("why") or "")[:2000]
            ops.append({"op": "save-phrase", "text": better[:1000], "translation": why, "kind": "expression", "title": title, "sentence": "", "url": ""})
    return ops


def push_tutoring(tutoring: dict, title: str) -> Optional[int]:
    """튜터링의 단어·고친 표현을 readgloss 단어장에 넣고 넣은 개수를 돌려준다. 다리가 없으면 None.

    readgloss는 같은 원형·같은 글을 다시 저장해도 항목 하나로 두고 복습 상태를 유지한다.
    """
    if _request("GET", "/ping") is None:
        return None
    return sum(1 for op in push_ops(tutoring, title) if _request("POST", "/words", op) is not None)

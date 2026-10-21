"""문화 DB 검색 결과 중 이 통화의 주제와 강하게 맞는 항목만 남긴다.

DB 전문 검색은 폭넓게 찾기 때문에 통화와 상관없는 일반 노트(예: 일 이야기 통화에 수영복 노트)가 섞인다.
기준은 통화의 topic_keywords와 thinking_gaps의 english뿐이다. 맞는 것이 없으면 빈 결과를 돌려준다.
"""

import re
from typing import Any, Dict, FrozenSet, List

from server.tutor import GENERIC_TOPIC_WORDS

MAX_BLEND = 2
MAX_BANK_PER_COUNTRY = 2
MAX_NOTES = 2
_MIN_STEM = 3


def _stem(word: str) -> str:
    if word.endswith("ing") and len(word) - 3 >= _MIN_STEM:
        word = word[:-3]
    elif word.endswith("ed") and len(word) - 2 >= _MIN_STEM:
        word = word[:-2]
    elif word.endswith("s") and not word.endswith("ss") and len(word) - 1 >= _MIN_STEM:
        word = word[:-1]
    return word[:-1] if word.endswith("e") and len(word) > _MIN_STEM else word


def stems_of(text: Any) -> FrozenSet[str]:
    """영어 내용어(3글자 이상, 일반어 제외)의 어간 집합."""
    if not isinstance(text, str):
        return frozenset()
    words = re.findall(r"[a-z]+", text.lower().replace("\u2019", "'"))
    return frozenset(_stem(w) for w in words if len(w) >= _MIN_STEM and w not in GENERIC_TOPIC_WORDS)


def anchor_terms(tutoring: Dict[str, Any]) -> List[FrozenSet[str]]:
    """통화 주제 기준 검색어: topic_keywords 각 항목과 thinking_gaps의 english 각 항목의 어간 집합."""
    texts: List[Any] = []
    keywords = tutoring.get("topic_keywords")
    texts += keywords if isinstance(keywords, list) else []
    for gap in tutoring.get("thinking_gaps") or []:
        texts.append(gap.get("english") if isinstance(gap, dict) else None)
    terms: List[FrozenSet[str]] = []
    for text in texts:
        stems = stems_of(text)
        if stems and stems not in terms:
            terms.append(stems)
    return terms


def is_relevant(terms: List[FrozenSet[str]], head: str, body: str = "") -> bool:
    """항목이 통화 주제와 강하게 맞는지.

    head(질문·분류·상황)와 body(본문)에 어간이 모두 들어 있는 기준어가 있어야 하고, 그중 낱말 둘 이상짜리 기준어가
    전부 맞거나(구 기준어 전체 일치), 서로 다른 기준어가 둘 이상 맞아야 통과한다. 낱말 하나짜리 기준어 하나만 맞는 항목은 버린다.
    """
    head_stems = stems_of(head)
    all_stems = head_stems | stems_of(body)
    matched = [t for t in terms if t <= all_stems]
    if not matched:
        return False
    return any(len(t) >= 2 for t in matched) or len(matched) >= 2


def filter_found(found: Dict[str, List[Dict[str, Any]]], tutoring: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """culturedb.search 결과에서 통화 주제와 맞는 항목만(BLEnD 3건, CultureBank 나라당 2건까지) 남긴다."""
    terms = anchor_terms(tutoring)
    if not terms:
        return {"blend": [], "bank": []}
    blend = [b for b in found.get("blend", []) if is_relevant(terms, str(b.get("question") or ""))][:MAX_BLEND]
    bank: List[Dict[str, Any]] = []
    per_country: Dict[str, int] = {}
    for b in found.get("bank", []):
        head = f"{b.get('topic') or ''} {b.get('context') or ''}"
        country = str(b.get("country") or "")
        if per_country.get(country, 0) >= MAX_BANK_PER_COUNTRY or not is_relevant(terms, head, str(b.get("text") or "")):
            continue
        per_country[country] = per_country.get(country, 0) + 1
        bank.append(b)
    blend = blend[:MAX_NOTES]
    return {"blend": blend, "bank": bank[: MAX_NOTES - len(blend)]}

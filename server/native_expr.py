"""원어민 표현(관용구·구동사·고정 덩어리·담화 표지) 목록을 읽고 고른다.

목록은 scripts/build_native_expressions.py가 만든 JSON 한 파일이다(NATIVE_EXPR_PATH로 바꿀 수 있다).
이 모듈은 파일을 읽기 전용으로만 연다. 어떤 시험이나 기본 경로에서도 학습 폴더에 쓰지 않는다.
- load: 파일을 검증해 읽는다(깨진 항목은 건너뛴다).
- lemma_key: 가벼운 원형 통일(ended up -> end up). 만드는 쪽과 고르는 쪽이 같은 함수를 쓴다.
- pick_for_friend: 친구 통화·채팅에 쓸 표현 2개(저장했지만 아직 안 쓴 표현을 먼저).
표준 라이브러리만 쓴다.
"""

import json
import logging
import os
import random
import re
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from server import known

logger = logging.getLogger(__name__)

PATH_ENV = "NATIVE_EXPR_PATH"
DEFAULT_PATH = Path.home() / "dev" / "learning" / "english" / "clipdb" / "native_expressions.json"
KINDS = ("idiom", "phrasal_verb", "chunk", "discourse_marker")
REGISTERS = ("casual", "neutral", "work")
FRIEND_COUNT = 2
FRIEND_POOL = 150
LEARNER_LABEL = "**Me:**"
TRANSCRIPT_FILES = 12
TRANSCRIPT_MAX_CHARS = 80000
# 피드 순서: 백만 낱말당 MID_MIN~MID_MAX번의 관용구·구동사가 앞, MID_MAX보다 흔한 기본 표현은 맨 뒤.
MID_MIN = 2.0
MID_MAX = 150.0
MID_KINDS = ("idiom", "phrasal_verb")
NGRAM_MAX = 8

_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)*")
_IRREGULAR = {
    "am": "be", "is": "be", "are": "be", "was": "be", "were": "be", "been": "be", "being": "be",
    "has": "have", "had": "have", "having": "have",
    "does": "do", "did": "do", "done": "do", "doing": "do",
    "goes": "go", "went": "go", "gone": "go", "going": "go",
    "got": "get", "gotten": "get", "came": "come", "took": "take", "taken": "take",
    "made": "make", "said": "say", "saw": "see", "seen": "see", "knew": "know", "known": "know",
    "thought": "think", "told": "tell", "found": "find", "gave": "give", "given": "give",
    "left": "leave", "kept": "keep", "felt": "feel", "brought": "bring", "began": "begin", "begun": "begin",
    "ran": "run", "held": "hold", "stood": "stand", "understood": "understand", "meant": "mean",
    "built": "build", "lost": "lose", "paid": "pay", "sent": "send", "spent": "spend", "sat": "sit",
    "wrote": "write", "written": "write", "spoke": "speak", "spoken": "speak", "broke": "break",
    "broken": "break", "chose": "choose", "chosen": "choose", "fell": "fall", "fallen": "fall",
    "drew": "draw", "drawn": "draw", "threw": "throw", "thrown": "throw", "grew": "grow", "grown": "grow",
    "ate": "eat", "eaten": "eat", "drove": "drive", "driven": "drive", "wore": "wear", "worn": "wear",
    "won": "win", "hung": "hang", "met": "meet", "led": "lead", "fed": "feed", "sold": "sell",
    "bought": "buy", "caught": "catch", "taught": "teach", "fought": "fight", "slept": "sleep",
    "forgot": "forget", "forgotten": "forget", "rose": "rise", "risen": "rise", "woke": "wake", "woken": "wake",
}
_E_ENDINGS = ("ur", "iv", "ov", "iz", "ak", "ag", "av")
_VOWELS = "aeiou"


def tokens(text: str) -> List[str]:
    return _TOKEN_RE.findall(str(text or "").lower().replace("\u2019", "'"))


def _stem(s: str) -> str:
    """-ing/-ed를 뗀 줄기를 다듬는다(running -> run, making -> make, figured -> figure)."""
    if len(s) >= 3 and s[-1] == s[-2] and s[-1] not in "aeioulsz":
        return s[:-1]
    if len(s) >= 2 and s[-2:] in _E_ENDINGS:
        return s + "e"
    if len(s) == 3 and s[-1] not in _VOWELS + "wxy" and s[-2] in _VOWELS and s[-3] not in _VOWELS:
        return s + "e"
    return s


def lemma_token(word: str) -> str:
    """낱말 하나의 가벼운 원형. 불규칙 동사 표와 -s/-es/-ed/-ing 규칙만 쓴다."""
    if word in _IRREGULAR:
        return _IRREGULAR[word]
    n = len(word)
    if "'" in word or n <= 3:
        return word
    if word.endswith("ies") and n > 4:
        return word[:-3] + "y"
    if word.endswith("ied") and n > 4:
        return word[:-3] + "y"
    if word.endswith("ing") and n > 5:
        return _stem(word[:-3])
    if word.endswith("ed") and n > 4:
        return _stem(word[:-2])
    if word.endswith(("sses", "ches", "shes", "xes", "zes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def lemma_tokens(text: str) -> List[str]:
    return [lemma_token(t) for t in tokens(text)]


def lemma_key(text: str) -> str:
    return " ".join(lemma_tokens(text))


def native_path() -> Path:
    override = os.getenv(PATH_ENV, "").strip()
    return Path(os.path.expanduser(override)) if override else DEFAULT_PATH


def _clean_clip(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    video_id, text = raw.get("video_id"), raw.get("text")
    try:
        start, end = float(raw.get("start")), float(raw.get("end"))
    except (TypeError, ValueError):
        return None
    if not isinstance(video_id, str) or not video_id or not isinstance(text, str) or not text.strip():
        return None
    return {
        "video_id": video_id,
        "start": start,
        "end": max(start, end),
        "text": text.strip(),
        "title": str(raw.get("title") or ""),
        "channel": str(raw.get("channel") or ""),
    }


def clean_entry(raw: Any) -> Optional[Dict[str, Any]]:
    """파일 항목 하나를 검증한다. 표현·뜻·클립이 하나라도 없으면 None."""
    if not isinstance(raw, dict):
        return None
    expression = " ".join(str(raw.get("expression") or "").split())
    meaning = " ".join(str(raw.get("meaning_ko") or "").split())
    kind = raw.get("kind")
    if not expression or not meaning or kind not in KINDS:
        return None
    clips = [c for c in (_clean_clip(x) for x in raw.get("clips") or []) if c]
    if not clips:
        return None
    register = raw.get("register") if raw.get("register") in REGISTERS else "neutral"
    try:
        per_million = max(0.0, float(raw.get("per_million") or 0.0))
    except (TypeError, ValueError):
        per_million = 0.0
    return {
        "expression": expression,
        "key": lemma_key(expression),
        "kind": kind,
        "meaning_ko": meaning,
        "why_hard": " ".join(str(raw.get("why_hard") or "").split()),
        "register": register,
        "example": " ".join(str(raw.get("example") or "").split()),
        "per_million": per_million,
        "count": int(raw.get("count") or 0),
        "clips": clips[:3],
    }


_CACHE_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {"sig": None, "entries": []}


def load(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """검증된 표현 목록(파일 순서 그대로). 파일이 없거나 깨졌으면 빈 목록. 파일이 바뀔 때만 다시 읽는다."""
    p = Path(path) if path else native_path()
    try:
        stat = p.stat()
    except OSError:
        return []
    sig = (str(p), stat.st_mtime_ns, stat.st_size)
    with _CACHE_LOCK:
        if _CACHE["sig"] == sig:
            return _CACHE["entries"]
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.error("원어민 표현 파일을 읽지 못했습니다 %s: %s", p, e)
        return []
    items = data.get("expressions") if isinstance(data, dict) else data
    entries = [e for e in (clean_entry(x) for x in items or []) if e]
    with _CACHE_LOCK:
        _CACHE["sig"] = sig
        _CACHE["entries"] = entries
    return entries


def eligible(entries: Iterable[Dict[str, Any]], known_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """알려 준 표현(known 저장소)에 든 표현은 제안에서 뺀다."""
    keys = known.keys_of(e["text"] for e in known.load(known_path))
    return [e for e in entries if not known.is_known(e["expression"], keys)]


def weighted_order(entries: Sequence[Dict[str, Any]], rng: random.Random) -> List[Dict[str, Any]]:
    """원어민 빈도에 비례해 앞에 올 확률이 높게 섞는다(가중 비복원 추출)."""
    keyed = []
    for e in entries:
        weight = max(e["per_million"], 0.01)
        keyed.append((rng.random() ** (1.0 / weight), e))
    keyed.sort(key=lambda pair: pair[0], reverse=True)
    return [e for _, e in keyed]


def _transcript_files(directory: Optional[Path]) -> List[Path]:
    from server.transcript_store import get_transcript_dir

    folder = Path(directory) if directory else get_transcript_dir()
    try:
        return sorted(folder.glob("*.md"), reverse=True)
    except OSError:
        return []


def _learner_lines(files: Iterable[Path]) -> List[str]:
    lines: List[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines += [ln[len(LEARNER_LABEL):].strip() for ln in text.splitlines() if ln.startswith(LEARNER_LABEL)]
    return lines


def recent_learner_text(directory: Optional[Path] = None) -> str:
    """최근 통화 전문에서 학습자(Me) 줄만 이어 붙인 글. 읽기 실패는 건너뛴다."""
    return "\n".join(_learner_lines(_transcript_files(directory)[:TRANSCRIPT_FILES]))[:TRANSCRIPT_MAX_CHARS]


def ngrams(tokens_: Sequence[str], max_n: int = NGRAM_MAX) -> Set[Tuple[str, ...]]:
    return {tuple(tokens_[i : i + n]) for n in range(1, max_n + 1) for i in range(len(tokens_) - n + 1)}


_USED_CACHE: Dict[str, Any] = {"sig": None, "grams": set()}


def learner_ngrams(directory: Optional[Path] = None) -> Set[Tuple[str, ...]]:
    """모든 통화 전문의 학습자(Me) 줄에 나온 낱말 묶음(원형 통일, 1~NGRAM_MAX낱말). 파일이 바뀔 때만 다시 만든다."""
    files = _transcript_files(directory)
    try:
        sig = tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files)
    except OSError:
        return set()
    with _CACHE_LOCK:
        if _USED_CACHE["sig"] == sig:
            return _USED_CACHE["grams"]
    grams: Set[Tuple[str, ...]] = set()
    for line in _learner_lines(files):
        grams |= ngrams(lemma_tokens(line))
    with _CACHE_LOCK:
        _USED_CACHE["sig"] = sig
        _USED_CACHE["grams"] = grams
    return grams


def unused_by_learner(entries: Iterable[Dict[str, Any]], used: Set[Tuple[str, ...]]) -> List[Dict[str, Any]]:
    """학습자가 자기 통화에서 이미 쓴 표현을 뺀다."""
    return [e for e in entries if tuple(e["key"].split()) not in used]


def native_tier(entry: Dict[str, Any]) -> int:
    """0: 중간 빈도 관용구·구동사(앞), 1: 그 밖의 표현, 2: 너무 흔한 기본 표현(뒤)."""
    if entry["per_million"] > MID_MAX:
        return 2
    return 0 if entry["kind"] in MID_KINDS and entry["per_million"] >= MID_MIN else 1


def native_order(entries: Sequence[Dict[str, Any]], rng: random.Random) -> List[Dict[str, Any]]:
    """tier 순서를 지키되 같은 tier 안에서는 빈도에 비례한 가중 섞기로 다양하게 낸다."""
    ordered: List[Dict[str, Any]] = []
    for tier in (0, 1, 2):
        ordered += weighted_order([e for e in entries if native_tier(e) == tier], rng)
    return ordered


def _contains_key(haystack_tokens: Sequence[str], key: str) -> bool:
    needle = key.split()
    n = len(needle)
    return n > 0 and any(list(haystack_tokens[i : i + n]) == needle for i in range(len(haystack_tokens) - n + 1))


def pick_for_friend(
    entries: Sequence[Dict[str, Any]],
    saved_phrases: Sequence[str],
    learner_text: str,
    count: int = FRIEND_COUNT,
    rng: Optional[random.Random] = None,
    known_path: Optional[Path] = None,
) -> List[Dict[str, str]]:
    """친구에게 줄 표현 count개 [{phrase, meaning}].

    일하는 자리 말투(work)와 알려 준 표현은 뺀다. 학습자가 저장했지만 최근 통화에서 아직 쓰지 않은 표현을 먼저 고르고,
    모자라면 학습자가 안 쓴 표현 중 원어민 빈도가 높은 것(상위 FRIEND_POOL개)에서 빈도에 비례해 뽑는다.
    """
    rng = rng or random.Random()
    pool = [e for e in eligible(entries, known_path) if e["register"] != "work"]
    if not pool:
        return []
    spoken = lemma_tokens(learner_text)
    saved_tokens = [lemma_tokens(p) for p in saved_phrases]
    unused = [e for e in pool if not _contains_key(spoken, e["key"])]
    saved_unused = [e for e in unused if any(_contains_key(toks, e["key"]) for toks in saved_tokens)]
    picked = weighted_order(saved_unused, rng)[:count]
    if len(picked) < count:
        taken = {e["key"] for e in picked}
        rest = sorted((e for e in unused if e["key"] not in taken), key=lambda e: e["per_million"], reverse=True)[:FRIEND_POOL]
        picked += weighted_order(rest, rng)[: count - len(picked)]
    return [{"phrase": e["expression"], "meaning": e["meaning_ko"]} for e in picked]

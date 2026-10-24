"""친구별(통화 상대별) 기억 파일 (기억 v2, docs/memory-v2.md).

PARTNER_MEMORY_DIR/<id>.json 에 친구가 학습자에 대해 알게 된 사실(facts), 다음에 이어 물을 거리(threads),
친구 자신의 이야기 진행(self_story), 같이 만든 농담(jokes), 대화별 짧은 요약(episodes), 하루 한 번 쓰는
"이 사람에 대해 아는 것" 문단(reflection)을 둔다.

v2의 사실(facts)은 개수 상한이 없다. 각 사실은 id, 중요도(1~5), 처음/마지막으로 본 날, 상태(valid/past),
끝난 날(until), 출처 통화(source)를 가진다. 사실이 달라지면 지우지 않고 past로 바꾼다.
갱신은 모델이 ADD/UPDATE/PAST/NOOP 연산을 돌려주고 코드가 검증해 적용한다(전체를 다시 쓰지 않는다).

v1 파일(날짜만 있는 facts, 새 키 없음)은 읽을 때 v2 모양으로 올려서 돌려주고, 처음 쓸 때 history/ 로 백업한 뒤
v2로 저장한다. Ms. Park과 Teach-back에는 기억이 없다.
쓰기 전에 history/<id>-<stamp>.json 으로 백업하고, 임시 파일 + os.replace로 원자적으로 쓴다.
"""

import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

MEMORY_DIR_ENV = "PARTNER_MEMORY_DIR"
DEFAULT_MEMORY_DIR = "~/dev/learning/english/partner-memory"
HISTORY_DIR_NAME = "history"
MEMORY_VERSION = 2

# src/lib/partners.ts 와 같은 id. 표시 이름은 프롬프트에만 쓴다.
PARTNER_NAMES: Dict[str, str] = {
    "priya": "Priya",
    "omar": "Omar",
    "lukas": "Lukas",
    "carmen": "Carmen",
    "jake": "Jake",
    "chloe": "Chloe",
    "brian": "Brian",
}
PARTNER_IDS = tuple(PARTNER_NAMES)
KINDS = ("facts", "threads", "self_story", "jokes", "episodes")
# 지우기 전 ?text= 확인에 쓰는, 항목별 대표 글 키.
TEXT_KEY = {"facts": "text", "threads": "text", "self_story": "progress", "jokes": "text", "episodes": "summary"}
MODES = ("call", "chat")

MAX_SELF_STORY = 8
MAX_JOKES = 5
MAX_EPISODES = 60  # v1은 12였다. 대화 요약은 사실로 이미 뽑혀 있으니 길게 두되 파일이 끝없이 크지는 않게 한다.
STORY_MAX = 60
PROGRESS_MAX = 160
JOKE_MAX = 100
SUMMARY_MAX = 200
MAX_THREADS = 5
FACT_MAX = 160  # v1은 120이었다. 넘으면 버리지 않고 단어 경계에서 자른다.
THREAD_MAX = 80
KO_MAX = 30
REFLECTION_MAX = 600
IMPORTANCE_MIN, IMPORTANCE_MAX, DEFAULT_IMPORTANCE = 1, 5, 3
STATUSES = ("valid", "past")
MAX_OPS = 60  # 한 번의 갱신에서 받는 사실 연산 수 상한(모델이 폭주해도 코드가 막는다)
PROMPT_VALID_FACTS = 250  # 갱신 프롬프트에 싣는 현재 사실 수 상한(중요도·최근 순)
PROMPT_PAST_FACTS = 20

KST = timezone(timedelta(hours=9))
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_FACT_ID_RE = re.compile(r"f(\d+)", re.ASCII)
# update()가 load -> 모델 호출 -> write 전체를 잡고 그 안에서 write_memory도 잡으므로 재진입 락이다.
_LOCK = threading.RLock()

# 연락처로 보이는 항목은 코드로 버린다: 이메일, 전화번호(숫자 7개 이상, 구분 기호 허용), URL.
_CONTACT_RES = (
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"\+?\d(?:[\s().\-]*\d){6,}"),
    re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|net|org|io|kr|co|app|dev)\b", re.IGNORECASE),
)


def _has_contact(*values: str) -> bool:
    return any(rx.search(v) for v in values for rx in _CONTACT_RES)


class MemoryError_(ValueError):
    """기억 파일을 읽을 수 없을 때."""


class MemoryChanged(Exception):
    """지우려는 항목의 글이 저장된 글과 다를 때(화면이 오래된 목록을 보고 있다)."""


def get_memory_dir() -> Path:
    return Path(os.path.expanduser(os.getenv(MEMORY_DIR_ENV) or DEFAULT_MEMORY_DIR))


def valid_partner(partner_id: Any) -> bool:
    return isinstance(partner_id, str) and partner_id in PARTNER_NAMES


def memory_path(partner_id: str) -> Path:
    if not valid_partner(partner_id):
        raise ValueError("알 수 없는 친구입니다")
    return get_memory_dir() / f"{partner_id}.json"


def _stamp(now: datetime) -> str:
    return now.astimezone(KST).strftime("%Y-%m-%dT%H:%M:%S%z")


def _today(now: datetime) -> str:
    return now.astimezone(KST).strftime("%Y-%m-%d")


def _clean(value: Any) -> str:
    return " ".join(value.split()) if isinstance(value, str) else ""


def _cut_words(text: str, limit: int) -> str:
    """limit 안으로 단어 경계에서 자른다(버리지 않는다)."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    if text[limit] != " ":  # 단어 한가운데면 마지막 단어를 뺀다
        head = cut.rsplit(" ", 1)
        cut = head[0] if len(head) == 2 else cut
    return cut.rstrip(" ,;:-")


_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def _cut_summary(text: str, limit: int) -> str:
    """limit 안에서 문장 끝으로 끝나게 자른다. 문장 끝이 없으면 단어 경계에서 자르고 '…'를 붙인다."""
    if len(text) <= limit:
        return text
    ends = [m.end() for m in _SENTENCE_END.finditer(text[:limit])]
    if ends:
        return text[: ends[-1]].rstrip()
    return _cut_words(text, limit - 1) + "…"


def _date(value: Any, fallback: str) -> str:
    if isinstance(value, str) and _DATE_RE.fullmatch(value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            pass
    return fallback


def _importance(value: Any, fallback: int = DEFAULT_IMPORTANCE) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return max(IMPORTANCE_MIN, min(IMPORTANCE_MAX, int(round(value))))


def _fact_num(fact_id: Any) -> Optional[int]:
    m = _FACT_ID_RE.fullmatch(fact_id) if isinstance(fact_id, str) else None
    return int(m.group(1)) if m else None


def _next_fact_id(facts: List[Dict[str, Any]]) -> str:
    return f"f{max([n for n in (_fact_num(f.get('id')) for f in facts) if n is not None] or [0]) + 1}"


def sort_facts(facts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """보여 주는 순서: 지금 맞는 사실(중요도 높은 순, 같으면 최근 순) 다음에 지난 사실(끝난 날 최근 순).

    저장 순서도 이 순서라서 화면의 목록 번호와 지우기 번호가 항상 같다."""
    valid = [f for f in facts if f["status"] == "valid"]
    past = [f for f in facts if f["status"] == "past"]
    valid.sort(key=lambda f: (f["importance"], f["last_seen"]), reverse=True)
    past.sort(key=lambda f: (f.get("until") or f["last_seen"]), reverse=True)
    return valid + past


def normalize_facts(items: Any, today: str) -> List[Dict[str, Any]]:
    """사실 목록을 v2 모양으로 맞춘다(개수 상한 없음).

    v1 항목(text, last_seen만 있음)은 중요도 3, 처음 본 날 = 마지막으로 본 날, valid로 올린다. id가 없거나 겹치면 새로 매긴다.
    글이 길면 버리지 않고 자르며, 같은 글(대소문자 무시)이 같은 상태로 겹치면 하나만 남긴다."""
    out: List[Dict[str, Any]] = []
    seen_ids = set()
    seen_text = set()
    pending: List[Dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        text = _cut_words(_clean(item.get("text")), FACT_MAX)
        if not text or _has_contact(text):
            continue
        status = item.get("status") if item.get("status") in STATUSES else "valid"
        key = (text.lower(), status)
        if key in seen_text:
            continue
        seen_text.add(key)
        last_seen = _date(item.get("last_seen"), today)
        first_seen = _date(item.get("first_seen"), last_seen)
        if first_seen > last_seen:
            first_seen = last_seen
        until = _date(item.get("until"), "") if status == "past" else ""
        source = item.get("source")
        fact = {
            "id": item.get("id"),
            "text": text,
            "importance": _importance(item.get("importance")),
            "first_seen": first_seen,
            "last_seen": last_seen,
            "status": status,
            "until": until or (last_seen if status == "past" else None),
            "source": source if isinstance(source, str) and source else None,
        }
        if _fact_num(fact["id"]) is not None and fact["id"] not in seen_ids:
            seen_ids.add(fact["id"])
            out.append(fact)
        else:
            pending.append(fact)
    for fact in pending:  # id가 없거나 겹친 항목은 마지막에 새 id를 받는다
        fact["id"] = _next_fact_id(out)
        out.append(fact)
    return sort_facts(out)


def normalize_reflection(value: Any, today: str) -> Optional[Dict[str, str]]:
    if not isinstance(value, dict):
        return None
    text = _cut_summary(_clean(value.get("text")), REFLECTION_MAX)
    if not text or _has_contact(text):
        return None
    return {"text": text, "date": _date(value.get("date"), today)}


def normalize(data: Any, partner_id: str, now: datetime) -> Dict[str, Any]:
    """모델 응답이나 파일 내용을 기억 모양으로 맞춘다: 길이·개수 상한(사실은 상한 없음), 날짜 보정, 중복 제거."""
    if not isinstance(data, dict):
        raise ValueError("기억이 JSON 객체가 아닙니다")
    today = _today(now)
    facts = normalize_facts(data.get("facts"), today)
    threads: List[Dict[str, str]] = []
    seen = set()
    for item in data.get("threads") or []:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("text"))
        ko = _clean(item.get("ko"))
        if not text or len(text) > THREAD_MAX or not ko or len(ko) > KO_MAX or text.lower() in seen or _has_contact(text, ko):
            continue
        seen.add(text.lower())
        threads.append({"text": text, "ko": ko, "last_seen": _date(item.get("last_seen"), today)})
    stories: List[Dict[str, str]] = []
    seen = set()
    for item in data.get("self_story") or []:
        if not isinstance(item, dict):
            continue
        story = _cut_words(_clean(item.get("story")), STORY_MAX)  # 길다고 이야기 항목을 버리지 않고 자른다
        progress = _cut_words(_clean(item.get("progress")), PROGRESS_MAX)
        if not story or not progress or story.lower() in seen or _has_contact(story, progress):
            continue
        seen.add(story.lower())
        stories.append({"story": story, "progress": progress, "last_seen": _date(item.get("last_seen"), today)})
    jokes: List[Dict[str, str]] = []
    seen = set()
    for item in data.get("jokes") or []:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("text"))
        if not text or len(text) > JOKE_MAX or text.lower() in seen or _has_contact(text):
            continue
        seen.add(text.lower())
        jokes.append({"text": text, "last_seen": _date(item.get("last_seen"), today)})
    episodes: List[Dict[str, str]] = []
    for item in data.get("episodes") or []:
        if not isinstance(item, dict):
            continue
        summary = _clean(item.get("summary"))
        mode = item.get("mode")
        if not summary or len(summary) > SUMMARY_MAX or mode not in MODES or _has_contact(summary):
            continue
        episodes.append({"date": _date(item.get("date"), today), "mode": mode, "summary": summary})
    # 최근에 본 것을 앞에 두고 상한까지만 남긴다(안정 정렬이라 같은 날짜는 모델이 준 순서).
    threads.sort(key=lambda t: t["last_seen"], reverse=True)
    stories.sort(key=lambda t: t["last_seen"], reverse=True)
    jokes.sort(key=lambda t: t["last_seen"], reverse=True)
    episodes.sort(key=lambda e: e["date"], reverse=True)
    return {
        "partner": partner_id,
        "version": MEMORY_VERSION,
        "updated": _stamp(now),
        "reflection": normalize_reflection(data.get("reflection"), today),
        "facts": facts,
        "threads": threads[:MAX_THREADS],
        "self_story": stories[:MAX_SELF_STORY],
        "jokes": jokes[:MAX_JOKES],
        "episodes": episodes[:MAX_EPISODES],
    }


def _upgrade(data: Dict[str, Any]) -> None:
    """읽은 기억을 v2 모양으로 올린다(메모리 안에서만. 파일은 처음 쓸 때 v2로 바뀐다)."""
    updated = data.get("updated")
    today = updated[:10] if isinstance(updated, str) and _DATE_RE.fullmatch(updated[:10]) else _today(datetime.now(KST))
    data["facts"] = normalize_facts(data.get("facts"), today)
    data["reflection"] = normalize_reflection(data.get("reflection"), today)
    data["version"] = MEMORY_VERSION


def load_memory(partner_id: str) -> Optional[Dict[str, Any]]:
    """기억을 읽는다. 파일이 없으면 None, 깨졌으면 MemoryError_. v1 파일은 v2 모양으로 올려서 돌려준다."""
    path = memory_path(partner_id)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as e:
        raise MemoryError_(f"기억을 읽을 수 없습니다 {path}: {e}") from e
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("partner") != partner_id:
            raise ValueError("partner 필드가 맞지 않습니다")
        updated = data.get("updated")
        if not isinstance(updated, str) or not updated:
            raise ValueError("updated가 없습니다")
        for key in KINDS:
            if key in ("facts", "threads") and not isinstance(data.get(key), list):
                raise ValueError(f"{key}가 목록이 아닙니다")
            if key in data and not isinstance(data[key], list):
                raise ValueError(f"{key}가 목록이 아닙니다")
    except ValueError as e:
        raise MemoryError_(f"기억 형식이 틀렸습니다 {path}: {e}") from e
    for key in KINDS:  # v1 파일: 새 키는 빈 목록
        data.setdefault(key, [])
    _upgrade(data)
    return data


def _write_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup(path: Path, partner_id: str, now: datetime) -> Optional[Path]:
    """기존 파일을 history/<id>-<stamp>.json 으로 복사한다. 파일이 없으면 None."""
    if not path.exists():
        return None
    directory = path.parent / HISTORY_DIR_NAME
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{partner_id}-{now.astimezone(KST).strftime('%Y%m%d-%H%M%S')}"
    target = directory / f"{base}.json"
    n = 1
    while target.exists():
        target = directory / f"{base}-{n}.json"
        n += 1
    target.write_bytes(path.read_bytes())
    return target


def write_memory(partner_id: str, data: Dict[str, Any], now: Optional[datetime] = None) -> None:
    now = now or datetime.now(KST)
    path = memory_path(partner_id)
    with _LOCK:
        _backup(path, partner_id, now)
        _write_atomic(path, data)


def clear_memory(partner_id: str, now: Optional[datetime] = None) -> None:
    """기억 파일을 지운다(백업 먼저). 파일이 없으면 아무것도 안 한다."""
    now = now or datetime.now(KST)
    path = memory_path(partner_id)
    with _LOCK:
        if not path.exists():
            return
        _backup(path, partner_id, now)
        path.unlink()


def forget_item(
    partner_id: str, kind: str, index: int, now: Optional[datetime] = None, text: Optional[str] = None
) -> Dict[str, Any]:
    """항목 하나를 지운다. 범위를 벗어나거나 기억이 없으면 IndexError, 종류가 틀리면 ValueError.

    text가 주어졌는데 저장된 항목의 글과 다르면 MemoryChanged(아무것도 지우지 않는다).
    지운 항목이 reflection 문단에 남아 있을 수 있으므로 문단도 함께 비운다(다음 갱신 때 새로 쓴다).
    """
    if kind not in KINDS:
        raise ValueError("kind는 facts, threads, self_story, jokes, episodes 중 하나여야 합니다")
    now = now or datetime.now(KST)
    path = memory_path(partner_id)
    with _LOCK:
        memory = load_memory(partner_id)
        if memory is None or not 0 <= index < len(memory[kind]):
            raise IndexError("해당 항목이 없습니다")
        if text is not None and memory[kind][index].get(TEXT_KEY[kind]) != text:
            raise MemoryChanged("기억이 바뀌었습니다")
        del memory[kind][index]
        memory["reflection"] = None
        memory["updated"] = _stamp(now)
        _backup(path, partner_id, now)
        _write_atomic(path, memory)
    return memory


def apply_fact_ops(
    facts: List[Dict[str, Any]], ops: Any, today: str, source: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """모델이 돌려준 사실 연산(ADD/UPDATE/PAST/NOOP)을 검증해 적용한다. 새 목록과 연산별 개수를 돌려준다.

    - ADD {text, importance}: 새 사실. 지금 맞는 사실과 글이 같으면 새로 만들지 않고 그 사실을 다시 본 것으로 친다.
    - UPDATE {id, text?, importance?}: 같은 사실을 다시 확인하거나 더 자세히 고친다. 지난(past) 사실이면 다시 valid로 되돌린다.
    - PAST {id, until?}: 더는 맞지 않는 사실. 지우지 않고 past와 끝난 날을 적는다.
    - NOOP과 알 수 없는 연산, 없는 id, 연락처가 든 글은 무시한다(개수는 'ignored'에 센다).
    """
    result = [dict(f) for f in facts]
    by_id = {f["id"]: f for f in result}
    counts = {"ADD": 0, "UPDATE": 0, "PAST": 0, "NOOP": 0, "ignored": 0}
    for op in (ops if isinstance(ops, list) else [])[:MAX_OPS]:
        kind = str(op.get("op", "")).strip().upper() if isinstance(op, dict) else ""
        if kind == "NOOP":
            counts["NOOP"] += 1
            continue
        if kind == "ADD":
            text = _cut_words(_clean(op.get("text")), FACT_MAX)
            if not text or _has_contact(text):
                counts["ignored"] += 1
                continue
            same = next((f for f in result if f["status"] == "valid" and f["text"].lower() == text.lower()), None)
            if same:
                same["last_seen"] = today
                same["importance"] = max(same["importance"], _importance(op.get("importance")))
            else:
                fact = {
                    "id": _next_fact_id(result),
                    "text": text,
                    "importance": _importance(op.get("importance")),
                    "first_seen": today,
                    "last_seen": today,
                    "status": "valid",
                    "until": None,
                    "source": source,
                }
                result.append(fact)
                by_id[fact["id"]] = fact
            counts["ADD"] += 1
        elif kind in ("UPDATE", "PAST"):
            fact = by_id.get(op.get("id")) if isinstance(op.get("id"), str) else None
            if fact is None:
                counts["ignored"] += 1
                continue
            if kind == "PAST":
                if fact["status"] == "valid":
                    fact["status"] = "past"
                    fact["until"] = max(_date(op.get("until"), today), fact["first_seen"])
                counts["PAST"] += 1
                continue
            if "text" in op:
                text = _cut_words(_clean(op.get("text")), FACT_MAX)
                if not text or _has_contact(text):
                    counts["ignored"] += 1
                    continue
                fact["text"] = text
            if "importance" in op:
                fact["importance"] = _importance(op.get("importance"), fact["importance"])
            fact["last_seen"] = today
            if fact["status"] == "past":  # 다시 맞는 말이 됐다
                fact["status"] = "valid"
                fact["until"] = None
            counts["UPDATE"] += 1
        else:
            counts["ignored"] += 1
    return sort_facts(result), counts


_SHAPE = """{
  "fact_ops": [
    {"op": "ADD", "text": "<English, <=160 chars>", "importance": 1-5},
    {"op": "UPDATE", "id": "<existing fact id>", "text": "<optional: better wording of the SAME fact>", "importance": 1-5},
    {"op": "PAST", "id": "<existing fact id>", "until": "YYYY-MM-DD"},
    {"op": "NOOP"}
  ],
  "threads": [{"text": "<English, <=80 chars>", "ko": "<Korean label, <=30 chars>", "last_seen": "YYYY-MM-DD"}],
  "self_story": [{"story": "<short English title, <=60 chars>", "progress": "<what the friend has told the learner so far, <=160 chars>", "last_seen": "YYYY-MM-DD"}],
  "jokes": [{"text": "<English, <=100 chars>", "last_seen": "YYYY-MM-DD"}],
  "episode": "<English summary of this conversation, <=200 chars>"%s
}"""
_REFLECTION_SHAPE = ',\n  "reflection": "<English paragraph, <=600 chars>"'


def format_transcript(turns: List[Tuple[str, str]]) -> str:
    """(speaker, text) 턴을 Me/Partner 줄로 만든다. speaker는 me/partner 어느 쪽이든 받는다."""
    lines = []
    for speaker, text in turns:
        label = "Me" if str(speaker).lower() == "me" else "Partner"
        if isinstance(text, str) and text.strip():
            lines.append(f"{label}: {text.strip()}")
    return "\n".join(lines)


def needs_reflection(old: Optional[Dict[str, Any]], today: str) -> bool:
    """오늘 아직 reflection 문단을 쓰지 않았으면 True(친구마다 하루 한 번)."""
    reflection = (old or {}).get("reflection")
    return not (isinstance(reflection, dict) and reflection.get("text") and reflection.get("date") == today)


def _facts_for_prompt(old: Optional[Dict[str, Any]]) -> str:
    facts = (old or {}).get("facts") or []
    valid = [f for f in facts if f["status"] == "valid"][:PROMPT_VALID_FACTS]  # 이미 중요도·최근 순
    past = [f for f in facts if f["status"] == "past"][:PROMPT_PAST_FACTS]
    lines = [f'{f["id"]} | importance {f["importance"]} | valid | last_seen {f["last_seen"]} | {f["text"]}' for f in valid]
    lines += [f'{f["id"]} | past since {f.get("until") or f["last_seen"]} | {f["text"]}' for f in past]
    return "\n".join(lines) if lines else "(none yet)"


def build_prompt(
    partner_id: str, old: Optional[Dict[str, Any]], turns: List[Tuple[str, str]], today: str, mode: str = "call",
    reflect: bool = False,
) -> str:
    name = PARTNER_NAMES[partner_id]
    old = old or {}
    other_json = json.dumps(
        {key: old.get(key, []) for key in ("threads", "self_story", "jokes")},
        ensure_ascii=False,
        indent=2,
    )
    kind = "text chat" if mode == "chat" else "phone call"
    reflection_rule = (
        f'\n- reflection = a short paragraph (at most {REFLECTION_MAX} characters, English, written about the learner in the third person) answering "what do I know about this person?": who they are, what they care about, what they are working on, and how they like to talk. Base it on all valid facts above plus this {kind}. No names, addresses or contact details.'
        if reflect
        else ""
    )
    return f"""You maintain the memory of {name}, a friendly conversation partner of an English learner (a Korean speaker). Today is {today}.
Update {name}'s memory after the {kind} below. Use ONLY this {kind}'s transcript for new information.
"Me" is the learner; "Partner" is {name}.

Known facts about the learner (id | importance | status | last_seen | text). This list grows over many months and is never rewritten:
{_facts_for_prompt(old)}

Other current memory (threads, self_story, jokes):
{other_json}

{kind.capitalize()} transcript:
---
{format_transcript(turns)}
---

Return ONLY a JSON object of exactly this shape:
{_SHAPE % (_REFLECTION_SHAPE if reflect else "")}

Rules:
- fact_ops = changes to the known facts list. Facts are what {name} learned about the learner (likes, plans, opinions, communities, small life events), based only on what the learner ("Me") said. Never record what the Partner said as a fact about the learner. Do not invent anything. Never rewrite the whole list; return only operations.
- ADD a fact only when the learner said something new that no known fact already covers. Write one short, self-contained sentence.
- UPDATE (by id) when the learner confirmed or refined a known fact. Give "text" only to improve the wording of the SAME fact; leave it out to just mark the fact as seen again.
- PAST (by id) when the learner said a known fact is no longer true (changed job, quit a hobby, the event is over). Then ADD the new fact if there is one. Facts are never deleted, so use PAST, not silence. "until" is the date it stopped being true (default today).
- NOOP when nothing in this {kind} changes the facts. If a known fact already says it, do not ADD it again.
- importance: 5 = who the learner is (family, faith, work or study, health, big plans); 4 = things they run or belong to, strong passions, important recurring routines; 3 = ordinary likes, opinions, one-off news worth recalling; 2 = minor preferences; 1 = trivia. Be generous with 4 for communities, clubs and long-term projects.
- threads = things {name} would naturally pick up next time (e.g. "the jazz concert on Saturday"). Add new ones from this {kind}. Drop threads that were resolved in it. Keep unresolved older threads.
- self_story = what {name} (Partner) told the learner about {name}'s OWN life: one entry per story, with a short title and "progress" = only the beats and concrete details {name} has actually told so far (older beats stay, new beats are added in order). Also record {name}'s ongoing bigger storyline when {name} has told one (e.g. a trek {name} is training for, a move, a job search) as its own entry, not only the small topic of the day. Record only what the Partner really said in this transcript or what the current memory already holds; never write a beat that was not told, and never finish a story the Partner only began.
- jokes = nicknames, running gags and playful bits that BOTH sides used and that could be reused. Keep it empty if there were none.
- episode = one short English summary of this {kind} (topics, what was decided, mood). Always provide it.
- threads, self_story and jokes: return the full current list merged with this {kind} (keep older items that are still true, update changed ones, remove duplicates). Set last_seen to {today} for items mentioned or confirmed in this {kind} and keep the old date for the rest.{reflection_rule}
- Write text in English. Every thread also needs a short Korean label in "ko" (at most 30 characters).
- Limits: facts have no count limit but each is at most {FACT_MAX} characters; {MAX_THREADS} threads at most (each at most {THREAD_MAX}), {MAX_SELF_STORY} self_story entries (story at most {STORY_MAX}, progress at most {PROGRESS_MAX}), {MAX_JOKES} jokes (each at most {JOKE_MAX}), episode at most {SUMMARY_MAX} characters.
- Privacy: never store real person names (including the learner's own), addresses, company or school names, phone numbers, emails or other contact details of the learner or the learner's acquaintances. Write "a coworker" or "the learner's friend" instead. Names of {name}'s own people inside {name}'s stories are fine.
- Faith: the learner's own faith, beliefs and religious practice are a normal personal topic, like hobbies or family. You may remember what the learner ("Me") said about it as a fact, and remember it respectfully: record it neutrally, never judge it, never argue with it, and never turn it into pressure to believe or to change. {name}'s own faith life inside {name}'s stories is fine.
- If nothing is worth remembering, return {{"fact_ops": [{{"op": "NOOP"}}], ...}} with the current threads, self_story and jokes unchanged (still with an episode)."""


def parse_model_json(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("빈 응답")
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    text = re.sub(r"\s*```$", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        raise ValueError("JSON 객체를 찾을 수 없습니다")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 아닙니다")
    return data


def update(
    partner_id: str,
    transcript_turns: List[Tuple[str, str]],
    generate_text: Callable[[str], Any],
    now: Optional[datetime] = None,
    mode: str = "call",
    source: Optional[str] = None,
) -> bool:
    """이번 대화(mode: call 또는 chat) 전문으로 친구 기억을 갱신한다. 성공하면 True.

    모델은 사실 연산(ADD/UPDATE/PAST/NOOP)과 threads·self_story·jokes 목록, 에피소드 한 줄을 돌려준다.
    오늘 아직 reflection 문단이 없으면 그것도 함께 쓰게 한다(친구마다 하루 한 번).
    어떤 단계가 실패해도 파일은 그대로 두고 로그만 남기고 False. 기존 파일이 깨졌으면 로그를 남기고 빈 기억에서
    시작한다(깨진 파일은 쓰기 직전에 history/ 로 백업된다). load -> 모델 호출 -> write를 락 하나로 묶어
    같은 친구의 두 갱신이 서로 덮어쓰지 못하게 한다. source는 이 대화의 출처(통화 전문 stem 등)로 새 사실에 적는다.
    """
    if not valid_partner(partner_id):
        logger.error("친구 기억 갱신 실패: 알 수 없는 친구 %r", partner_id)
        return False
    if mode not in MODES:
        logger.error("친구 기억 갱신 실패: 알 수 없는 mode %r", mode)
        return False
    now = now or datetime.now(KST)
    today = _today(now)
    try:
        if not any(str(s).lower() == "me" and isinstance(t, str) and t.strip() for s, t in transcript_turns):
            logger.info("친구 기억 갱신 건너뜀(%s): 학습자 발화 없음", partner_id)
            return False
        with _LOCK:
            try:
                old = load_memory(partner_id)
            except MemoryError_ as e:
                logger.error("친구 기억 파일이 깨져 빈 기억에서 다시 시작(%s, 원본은 history/ 로 백업): %s", partner_id, e)
                old = None
            reflect = needs_reflection(old, today)
            raw = generate_text(build_prompt(partner_id, old, transcript_turns, today, mode, reflect))
            data = parse_model_json(raw)
            facts, counts = apply_fact_ops((old or {}).get("facts") or [], data.get("fact_ops"), today, source or f"{mode}-{today}")
            logger.info("친구 기억 사실 연산(%s): %s", partner_id, counts)
            # 에피소드는 모델이 옛 것을 다시 쓰지 않는다: 옛 목록 앞에 이번 대화 하나만 붙인다.
            episodes = list((old or {}).get("episodes") or [])
            # 모델이 길게 쓰면 버리지 말고 문장 끝에서(없으면 단어 경계에서 …) 자른다
            summary = _cut_summary(_clean(data.get("episode")), SUMMARY_MAX)
            # 모델이 목록 키를 빼면 그 목록은 옛 것을 그대로 둔다(빈 목록으로 지우지 않는다)
            for key in ("threads", "self_story", "jokes"):
                if not isinstance(data.get(key), list):
                    data[key] = list((old or {}).get(key) or [])
            if summary:
                episodes.insert(0, {"date": today, "mode": mode, "summary": summary})
            reflection = (old or {}).get("reflection")
            if reflect:  # 모델이 문단을 못 쓰면 옛 문단을 두고 다음 갱신 때 다시 시도한다
                fresh = normalize_reflection({"text": data.get("reflection"), "date": today}, today)
                reflection = fresh or reflection
            new = normalize({**data, "facts": facts, "episodes": episodes, "reflection": reflection}, partner_id, now)
            write_memory(partner_id, new, now)
    except Exception as e:  # noqa: BLE001 - 기억 갱신은 부가 기능, 파일은 그대로
        logger.error("친구 기억 갱신 실패(%s, 파일은 그대로): %s", partner_id, e)
        return False
    return True

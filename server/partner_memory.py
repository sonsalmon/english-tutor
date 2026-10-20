"""친구별(통화 상대별) 기억 파일.

PARTNER_MEMORY_DIR/<id>.json 에 친구가 학습자에 대해 알게 된 사실(facts)과
다음에 이어 물을 거리(threads)를 둔다. Ms. Park과 Teach-back에는 기억이 없다.
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

# src/lib/partners.ts 와 같은 id. 표시 이름은 프롬프트에만 쓴다.
PARTNER_NAMES: Dict[str, str] = {
    "priya": "Priya",
    "omar": "Omar",
    "lukas": "Lukas",
    "carmen": "Carmen",
    "jake": "Jake",
    "chloe": "Chloe",
}
PARTNER_IDS = tuple(PARTNER_NAMES)
KINDS = ("facts", "threads")

MAX_FACTS = 12
MAX_THREADS = 5
FACT_MAX = 120
THREAD_MAX = 80
KO_MAX = 30

KST = timezone(timedelta(hours=9))
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
_LOCK = threading.Lock()


class MemoryError_(ValueError):
    """기억 파일을 읽을 수 없을 때."""


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


def _date(value: Any, fallback: str) -> str:
    if isinstance(value, str) and _DATE_RE.fullmatch(value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            pass
    return fallback


def normalize(data: Any, partner_id: str, now: datetime) -> Dict[str, Any]:
    """모델 응답이나 파일 내용을 기억 모양으로 맞춘다: 길이·개수 상한, 날짜 보정, 중복 제거."""
    if not isinstance(data, dict):
        raise ValueError("기억이 JSON 객체가 아닙니다")
    today = _today(now)
    facts: List[Dict[str, str]] = []
    seen = set()
    for item in data.get("facts") or []:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("text"))
        if not text or len(text) > FACT_MAX or text.lower() in seen:
            continue
        seen.add(text.lower())
        facts.append({"text": text, "last_seen": _date(item.get("last_seen"), today)})
    threads: List[Dict[str, str]] = []
    seen = set()
    for item in data.get("threads") or []:
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("text"))
        ko = _clean(item.get("ko"))
        if not text or len(text) > THREAD_MAX or not ko or len(ko) > KO_MAX or text.lower() in seen:
            continue
        seen.add(text.lower())
        threads.append({"text": text, "ko": ko, "last_seen": _date(item.get("last_seen"), today)})
    # 최근에 본 것을 앞에 두고 상한까지만 남긴다(안정 정렬이라 같은 날짜는 모델이 준 순서).
    facts.sort(key=lambda f: f["last_seen"], reverse=True)
    threads.sort(key=lambda t: t["last_seen"], reverse=True)
    return {
        "partner": partner_id,
        "updated": _stamp(now),
        "facts": facts[:MAX_FACTS],
        "threads": threads[:MAX_THREADS],
    }


def load_memory(partner_id: str) -> Optional[Dict[str, Any]]:
    """기억을 읽는다. 파일이 없으면 None, 깨졌으면 MemoryError_."""
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
            if not isinstance(data.get(key), list):
                raise ValueError(f"{key}가 목록이 아닙니다")
    except ValueError as e:
        raise MemoryError_(f"기억 형식이 틀렸습니다 {path}: {e}") from e
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


def forget_item(partner_id: str, kind: str, index: int, now: Optional[datetime] = None) -> Dict[str, Any]:
    """항목 하나를 지운다. 범위를 벗어나거나 기억이 없으면 IndexError, 종류가 틀리면 ValueError."""
    if kind not in KINDS:
        raise ValueError("kind는 facts 또는 threads여야 합니다")
    now = now or datetime.now(KST)
    path = memory_path(partner_id)
    with _LOCK:
        memory = load_memory(partner_id)
        if memory is None or not 0 <= index < len(memory[kind]):
            raise IndexError("해당 항목이 없습니다")
        del memory[kind][index]
        memory["updated"] = _stamp(now)
        _backup(path, partner_id, now)
        _write_atomic(path, memory)
    return memory


_SHAPE = """{
  "facts": [{"text": "<English, <=120 chars>", "last_seen": "YYYY-MM-DD"}],
  "threads": [{"text": "<English, <=80 chars>", "ko": "<Korean label, <=30 chars>", "last_seen": "YYYY-MM-DD"}]
}"""


def format_transcript(turns: List[Tuple[str, str]]) -> str:
    """(speaker, text) 턴을 Me/Partner 줄로 만든다. speaker는 me/partner 어느 쪽이든 받는다."""
    lines = []
    for speaker, text in turns:
        label = "Me" if str(speaker).lower() == "me" else "Partner"
        if isinstance(text, str) and text.strip():
            lines.append(f"{label}: {text.strip()}")
    return "\n".join(lines)


def build_prompt(partner_id: str, old: Optional[Dict[str, Any]], turns: List[Tuple[str, str]], today: str) -> str:
    name = PARTNER_NAMES[partner_id]
    old_json = json.dumps(
        {"facts": (old or {}).get("facts", []), "threads": (old or {}).get("threads", [])},
        ensure_ascii=False,
        indent=2,
    )
    return f"""You maintain the memory of {name}, a friendly conversation partner of an English learner (a Korean speaker). Today is {today}.
Update {name}'s memory after the phone call below. Use ONLY this call's transcript for new information.
"Me" is the learner; "Partner" is {name}.

Current memory:
{old_json}

Call transcript:
---
{format_transcript(turns)}
---

Return ONLY a JSON object of exactly this shape:
{_SHAPE}

Rules:
- facts = what {name} learned about the learner (likes, plans, opinions, small life events), based only on what the learner ("Me") said. Never record what the Partner said as a fact about the learner. Do not invent anything.
- threads = things {name} would naturally pick up next time (e.g. "the jazz concert on Saturday"). Add new ones from this call. Drop threads that were resolved in this call. Keep unresolved older threads.
- Merge with the current memory: keep older facts that are still true, update changed ones, remove duplicates. Set last_seen to {today} for items mentioned or confirmed in this call and keep the old date for the rest.
- Write text in English. Every thread also needs a short Korean label in "ko" (at most 30 characters).
- Limits: at most {MAX_FACTS} facts (each at most {FACT_MAX} characters) and at most {MAX_THREADS} threads (each at most {THREAD_MAX} characters). If over the limit, drop the least important or oldest.
- Privacy: never store real person names (including the learner's own), addresses, company or school names, phone numbers, emails or other contact details. Write "a coworker" or "the learner's friend" instead.
- If the learner said nothing worth remembering, return the current memory unchanged."""


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
) -> bool:
    """이번 통화 전문으로 친구 기억을 갱신한다. 성공하면 True.

    어떤 단계가 실패해도 파일은 그대로 두고 로그만 남기고 False.
    """
    if not valid_partner(partner_id):
        logger.error("친구 기억 갱신 실패: 알 수 없는 친구 %r", partner_id)
        return False
    now = now or datetime.now(KST)
    try:
        if not any(str(s).lower() == "me" and isinstance(t, str) and t.strip() for s, t in transcript_turns):
            logger.info("친구 기억 갱신 건너뜀(%s): 학습자 발화 없음", partner_id)
            return False
        old = load_memory(partner_id)
        raw = generate_text(build_prompt(partner_id, old, transcript_turns, _today(now)))
        new = normalize(parse_model_json(raw), partner_id, now)
        write_memory(partner_id, new, now)
    except Exception as e:  # noqa: BLE001 - 기억 갱신은 부가 기능, 파일은 그대로
        logger.error("친구 기억 갱신 실패(%s, 파일은 그대로): %s", partner_id, e)
        return False
    return True

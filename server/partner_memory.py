"""친구별(통화 상대별) 기억 파일.

PARTNER_MEMORY_DIR/<id>.json 에 친구가 학습자에 대해 알게 된 사실(facts), 다음에 이어 물을 거리(threads),
친구 자신의 이야기 진행(self_story), 같이 만든 농담(jokes), 대화별 짧은 요약(episodes)을 둔다.
v1 파일(새 키 없음)은 새 키를 빈 목록으로 읽는다. Ms. Park과 Teach-back에는 기억이 없다.
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
KINDS = ("facts", "threads", "self_story", "jokes", "episodes")
# 지우기 전 ?text= 확인에 쓰는, 항목별 대표 글 키.
TEXT_KEY = {"facts": "text", "threads": "text", "self_story": "progress", "jokes": "text", "episodes": "summary"}
MODES = ("call", "chat")

MAX_SELF_STORY = 8
MAX_JOKES = 5
MAX_EPISODES = 12
STORY_MAX = 60
PROGRESS_MAX = 160
JOKE_MAX = 100
SUMMARY_MAX = 200
MAX_FACTS = 12
MAX_THREADS = 5
FACT_MAX = 120
THREAD_MAX = 80
KO_MAX = 30

KST = timezone(timedelta(hours=9))
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
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
        if not text or len(text) > FACT_MAX or text.lower() in seen or _has_contact(text):
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
    facts.sort(key=lambda f: f["last_seen"], reverse=True)
    threads.sort(key=lambda t: t["last_seen"], reverse=True)
    stories.sort(key=lambda t: t["last_seen"], reverse=True)
    jokes.sort(key=lambda t: t["last_seen"], reverse=True)
    episodes.sort(key=lambda e: e["date"], reverse=True)
    return {
        "partner": partner_id,
        "updated": _stamp(now),
        "facts": facts[:MAX_FACTS],
        "threads": threads[:MAX_THREADS],
        "self_story": stories[:MAX_SELF_STORY],
        "jokes": jokes[:MAX_JOKES],
        "episodes": episodes[:MAX_EPISODES],
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
            if key in ("facts", "threads") and not isinstance(data.get(key), list):
                raise ValueError(f"{key}가 목록이 아닙니다")
            if key in data and not isinstance(data[key], list):
                raise ValueError(f"{key}가 목록이 아닙니다")
    except ValueError as e:
        raise MemoryError_(f"기억 형식이 틀렸습니다 {path}: {e}") from e
    for key in KINDS:  # v1 파일: 새 키는 빈 목록
        data.setdefault(key, [])
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
        memory["updated"] = _stamp(now)
        _backup(path, partner_id, now)
        _write_atomic(path, memory)
    return memory


_SHAPE = """{
  "facts": [{"text": "<English, <=120 chars>", "last_seen": "YYYY-MM-DD"}],
  "threads": [{"text": "<English, <=80 chars>", "ko": "<Korean label, <=30 chars>", "last_seen": "YYYY-MM-DD"}],
  "self_story": [{"story": "<short English title, <=60 chars>", "progress": "<what the friend has told the learner so far, <=160 chars>", "last_seen": "YYYY-MM-DD"}],
  "jokes": [{"text": "<English, <=100 chars>", "last_seen": "YYYY-MM-DD"}],
  "episode": "<English summary of this conversation, <=200 chars>"
}"""


def format_transcript(turns: List[Tuple[str, str]]) -> str:
    """(speaker, text) 턴을 Me/Partner 줄로 만든다. speaker는 me/partner 어느 쪽이든 받는다."""
    lines = []
    for speaker, text in turns:
        label = "Me" if str(speaker).lower() == "me" else "Partner"
        if isinstance(text, str) and text.strip():
            lines.append(f"{label}: {text.strip()}")
    return "\n".join(lines)


def build_prompt(
    partner_id: str, old: Optional[Dict[str, Any]], turns: List[Tuple[str, str]], today: str, mode: str = "call"
) -> str:
    name = PARTNER_NAMES[partner_id]
    old = old or {}
    old_json = json.dumps(
        {key: old.get(key, []) for key in ("facts", "threads", "self_story", "jokes")},
        ensure_ascii=False,
        indent=2,
    )
    kind = "text chat" if mode == "chat" else "phone call"
    return f"""You maintain the memory of {name}, a friendly conversation partner of an English learner (a Korean speaker). Today is {today}.
Update {name}'s memory after the {kind} below. Use ONLY this {kind}'s transcript for new information.
"Me" is the learner; "Partner" is {name}.

Current memory:
{old_json}

{kind.capitalize()} transcript:
---
{format_transcript(turns)}
---

Return ONLY a JSON object of exactly this shape:
{_SHAPE}

Rules:
- facts = what {name} learned about the learner (likes, plans, opinions, small life events), based only on what the learner ("Me") said. Never record what the Partner said as a fact about the learner. Do not invent anything.
- threads = things {name} would naturally pick up next time (e.g. "the jazz concert on Saturday"). Add new ones from this {kind}. Drop threads that were resolved in it. Keep unresolved older threads.
- self_story = what {name} (Partner) told the learner about {name}'s OWN life: one entry per story, with a short title and "progress" = only the beats and concrete details {name} has actually told so far (older beats stay, new beats are added in order). Also record {name}'s ongoing bigger storyline when {name} has told one (e.g. a trek {name} is training for, a move, a job search) as its own entry, not only the small topic of the day. Record only what the Partner really said in this transcript or what the current memory already holds; never write a beat that was not told, and never finish a story the Partner only began.
- jokes = nicknames, running gags and playful bits that BOTH sides used and that could be reused. Keep it empty if there were none.
- episode = one short English summary of this {kind} (topics, what was decided, mood). Always provide it.
- Merge with the current memory: keep older items that are still true, update changed ones, remove duplicates. Set last_seen to {today} for items mentioned or confirmed in this {kind} and keep the old date for the rest.
- Write text in English. Every thread also needs a short Korean label in "ko" (at most 30 characters).
- Limits: at most {MAX_FACTS} facts (each at most {FACT_MAX} characters), {MAX_THREADS} threads (each at most {THREAD_MAX}), {MAX_SELF_STORY} self_story entries (story at most {STORY_MAX}, progress at most {PROGRESS_MAX}), {MAX_JOKES} jokes (each at most {JOKE_MAX}), episode at most {SUMMARY_MAX} characters. If over the limit, drop the least important or oldest.
- Privacy: never store real person names (including the learner's own), addresses, company or school names, phone numbers, emails or other contact details of the learner or the learner's acquaintances. Write "a coworker" or "the learner's friend" instead. Names of {name}'s own people inside {name}'s stories are fine.
- If nothing is worth remembering, return the current memory unchanged (still with an episode)."""


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
) -> bool:
    """이번 대화(mode: call 또는 chat) 전문으로 친구 기억을 갱신한다. 성공하면 True.

    어떤 단계가 실패해도 파일은 그대로 두고 로그만 남기고 False. 기존 파일이 깨졌으면 로그를 남기고 빈 기억에서
    시작한다(깨진 파일은 쓰기 직전에 history/ 로 백업된다). load -> 모델 호출 -> write를 락 하나로 묶어
    같은 친구의 두 갱신이 서로 덮어쓰지 못하게 한다.
    """
    if not valid_partner(partner_id):
        logger.error("친구 기억 갱신 실패: 알 수 없는 친구 %r", partner_id)
        return False
    if mode not in MODES:
        logger.error("친구 기억 갱신 실패: 알 수 없는 mode %r", mode)
        return False
    now = now or datetime.now(KST)
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
            raw = generate_text(build_prompt(partner_id, old, transcript_turns, _today(now), mode))
            data = parse_model_json(raw)
            # 에피소드는 모델이 옛 것을 다시 쓰지 않는다: 옛 목록 앞에 이번 대화 하나만 붙인다.
            episodes = list((old or {}).get("episodes") or [])
            # 모델이 길게 쓰면 버리지 말고 문장 끝에서(없으면 단어 경계에서 …) 자른다
            summary = _cut_summary(_clean(data.get("episode")), SUMMARY_MAX)
            # 모델이 목록 키를 빼면 그 목록은 옛 것을 그대로 둔다(빈 목록으로 지우지 않는다)
            for key in ("facts", "threads", "self_story", "jokes"):
                if not isinstance(data.get(key), list):
                    data[key] = list((old or {}).get(key) or [])
            if summary:
                episodes.insert(0, {"date": _today(now), "mode": mode, "summary": summary})
            new = normalize({**data, "episodes": episodes}, partner_id, now)
            write_memory(partner_id, new, now)
    except Exception as e:  # noqa: BLE001 - 기억 갱신은 부가 기능, 파일은 그대로
        logger.error("친구 기억 갱신 실패(%s, 파일은 그대로): %s", partner_id, e)
        return False
    return True

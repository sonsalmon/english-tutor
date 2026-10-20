"""학습자 카드(learner-profile.json): 읽기·검사·갱신·영어 요약.

명세 docs/spec.md 4·5절. 통화 뒤 튜터링 JSON을 받아 모델이 카드 전체를 다시 쓰고,
코드가 형식과 불변 조건을 강제한다. 표준 라이브러리만 쓰며 server.* 를 가져오지
않는다(단위 시험이 server/ 안에서 바로 돈다).
"""

import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PROFILE_PATH_ENV = "LEARNER_PROFILE_PATH"
DEFAULT_PROFILE_PATH = "~/dev/learning/english/learner-profile.json"
HISTORY_DIR_NAME = "learner-profile-history"

MAX_WEAK_POINTS = 5
MAX_THINKING_GAPS = 8
GAP_KINDS = ("word", "framing")
BRIEF_GAPS = 3
RECYCLE_PREFIX = "Expressions to recycle (the learner recently reached for these in Korean): "
# 최근 이 횟수만큼 연속으로 통화에서 안 나오면 weak_points -> fixed_points
MISS_LIMIT = 3
BRIEF_MAX_CHARS = 1200

KST = timezone(timedelta(hours=9))  # Asia/Seoul (서머타임 없음)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)

# 같은 카드를 동시에 갱신하는 경합(두 통화 요약이 겹칠 때)을 막는다.
_UPDATE_LOCK = threading.Lock()


class ProfileError(ValueError):
    """카드가 4절 형식이 아니거나 읽을 수 없을 때."""


def get_profile_path() -> Path:
    return Path(os.path.expanduser(os.getenv(PROFILE_PATH_ENV) or DEFAULT_PROFILE_PATH))


def get_history_dir(path: Optional[Path] = None) -> Path:
    return (Path(path) if path else get_profile_path()).parent / HISTORY_DIR_NAME


def empty_profile(now: Optional[datetime] = None) -> Dict[str, Any]:
    return {
        "updated": _stamp(now),
        "level": {"cefr": "", "actfl": "", "source": ""},
        "weak_points": [],
        "fixed_points": [],
        "phrases": [],
        "pragmatics": [],
        "interests": [],
        "next_goal": "",
        "thinking_gaps": [],
    }


def _stamp(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(KST)).astimezone(KST).isoformat(timespec="seconds")


def _fail(where: str, why: str) -> None:
    raise ProfileError(f"{where}: {why}")


def _str(obj: Any, key: str, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        _fail(where, f"'{key}'는 문자열이어야 합니다")
    return value


def _int(obj: Any, key: str, where: str) -> int:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(where, f"'{key}'는 0 이상의 정수여야 합니다")
    return value


def _date(obj: Any, key: str, where: str) -> str:
    value = _str(obj, key, where)
    if not _DATE_RE.fullmatch(value):
        _fail(where, f"'{key}'는 YYYY-MM-DD여야 합니다")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        _fail(where, f"'{key}'가 실제 날짜가 아닙니다")
    return value


def _obj(value: Any, keys: set, where: str, optional: frozenset = frozenset()) -> Dict[str, Any]:
    if not isinstance(value, dict):
        _fail(where, "객체여야 합니다")
    missing = keys - set(value)
    extra = set(value) - keys - optional
    if missing or extra:
        _fail(where, f"키가 맞지 않습니다 (없음 {sorted(missing)}, 여분 {sorted(extra)})")
    return value


def _list(card: Dict[str, Any], key: str) -> List[Any]:
    value = card[key]
    if not isinstance(value, list):
        _fail(key, "배열이어야 합니다")
    return value


def _point(item: Any, where: str) -> Dict[str, Any]:
    _obj(item, {"pattern", "count", "last_seen", "example"}, where, frozenset({"misses"}))
    out = {
        "pattern": _str(item, "pattern", where),
        "count": _int(item, "count", where),
        "last_seen": _date(item, "last_seen", where),
        "example": _str(item, "example", where),
        "misses": _int(item, "misses", where) if "misses" in item else 0,
    }
    if not out["pattern"].strip():
        _fail(where, "'pattern'이 비었습니다")
    return out


def _gap(item: Any, where: str) -> Dict[str, Any]:
    _obj(item, {"korean", "english", "kind", "note", "count", "last_seen"}, where)
    out = {
        "korean": _str(item, "korean", where),
        "english": _str(item, "english", where),
        "kind": _str(item, "kind", where),
        "note": _str(item, "note", where),
        "count": _int(item, "count", where),
        "last_seen": _date(item, "last_seen", where),
    }
    if out["kind"] not in GAP_KINDS:
        _fail(where, "'kind'는 word 또는 framing이어야 합니다")
    if not out["korean"].strip() or not out["english"].strip():
        _fail(where, "'korean'과 'english'가 비었습니다")
    return out


def _gap_key(text: Any) -> str:
    """비교용 키: 소문자로 바꾸고 공백·기호를 버린다(한글은 그대로 남긴다)."""
    return re.sub(r"[\W_]+", "", str(text).lower())


def _gap_order(g: Dict[str, Any]) -> tuple:
    return (g["count"], g["last_seen"])


def _sort_gaps(gaps: List[Dict[str, Any]], protected: frozenset = frozenset()) -> List[Dict[str, Any]]:
    """count 내림차순, 같으면 최근 순으로 8개까지. protected(id) 항목은 상한에서 먼저 살린다."""
    kept = [g for g in gaps if id(g) in protected][:MAX_THINKING_GAPS]
    rest = sorted((g for g in gaps if id(g) not in protected), key=_gap_order, reverse=True)
    kept += rest[: MAX_THINKING_GAPS - len(kept)]
    return sorted(kept, key=_gap_order, reverse=True)


def merge_thinking_gaps(old: List[Dict[str, Any]], new: Any, today: str) -> List[Dict[str, Any]]:
    """통화 분석의 thinking_gaps를 카드 항목에 결정적으로 합친다(코드 소유).

    같은 항목 = english 정규화가 같거나 korean 정규화가 같은 것. 통화 하나당 한 번만 count+1,
    last_seen·note는 최신 값으로, kind는 한 번 framing이면 framing을 유지한다. 새 항목은 count 1.
    count 내림차순, 같으면 최근 순, 8개로 자른다. 이번 통화에서 만난 항목은 상한에서 보호하고
    count가 낮고 오래된 안 만난 항목부터 버린다. 형식이 틀린 새 항목은 건너뛴다.
    """
    merged = [dict(g) for g in old]
    touched: set = set()  # merged 안의 위치
    for item in new if isinstance(new, list) else []:
        if not isinstance(item, dict):
            continue
        korean, english = item.get("korean"), item.get("english")
        kind, note = item.get("kind"), item.get("note")
        if not (isinstance(korean, str) and isinstance(english, str) and kind in GAP_KINDS):
            continue
        korean, english = korean.strip(), english.strip()
        note = note.strip() if isinstance(note, str) else ""
        ek, kk = _gap_key(english), _gap_key(korean)
        if not ek or not kk:
            continue
        found = next(
            (i for i, g in enumerate(merged) if _gap_key(g["english"]) == ek or _gap_key(g["korean"]) == kk),
            None,
        )
        if found is None:
            merged.append(
                {"korean": korean, "english": english, "kind": kind, "note": note, "count": 1, "last_seen": today}
            )
            touched.add(len(merged) - 1)
            continue
        gap = merged[found]
        if found not in touched:
            gap["count"] += 1
            touched.add(found)
        gap["last_seen"] = today
        if gap["kind"] != "framing":  # framing은 한 번 되면 유지
            gap["kind"] = kind
        if note:
            gap["note"] = note
    return _sort_gaps(merged, frozenset(id(merged[i]) for i in touched))


def validate_profile(card: Any) -> Dict[str, Any]:
    """4절 형식을 엄격히 검사하고 정리된 새 dict를 돌려준다. 틀리면 ProfileError.

    weak_points·fixed_points 항목은 같은 모양(pattern·count·last_seen·example)이고,
    weak_points에는 선택 정수 `misses`(이 패턴이 연속으로 안 나온 통화 수)가 있다.
    정리 결과의 모든 weak_points 항목에는 misses가 들어간다(없으면 0).
    """
    _obj(
        card,
        {"updated", "level", "weak_points", "fixed_points", "phrases", "pragmatics", "interests", "next_goal"},
        "카드",
        frozenset({"thinking_gaps"}),  # 옛 카드에는 없다 -> []
    )
    updated = _str(card, "updated", "updated")
    try:
        datetime.fromisoformat(updated)
    except ValueError:
        _fail("updated", "ISO 8601 시각이어야 합니다")

    level = _obj(card["level"], {"cefr", "actfl", "source"}, "level")
    out: Dict[str, Any] = {
        "updated": updated,
        "level": {k: _str(level, k, "level") for k in ("cefr", "actfl", "source")},
        "weak_points": [_point(p, f"weak_points[{i}]") for i, p in enumerate(_list(card, "weak_points"))],
        "fixed_points": [],
        "phrases": [],
        "pragmatics": [],
        "interests": [],
        "next_goal": _str(card, "next_goal", "next_goal"),
        "thinking_gaps": [],
    }
    if "thinking_gaps" in card:
        out["thinking_gaps"] = [_gap(g, f"thinking_gaps[{i}]") for i, g in enumerate(_list(card, "thinking_gaps"))]
    for i, p in enumerate(_list(card, "fixed_points")):
        point = _point(p, f"fixed_points[{i}]")
        point.pop("misses")
        out["fixed_points"].append(point)
    for i, p in enumerate(_list(card, "phrases")):
        w = f"phrases[{i}]"
        _obj(p, {"phrase", "first_seen", "used_well"}, w)
        out["phrases"].append(
            {"phrase": _str(p, "phrase", w), "first_seen": _date(p, "first_seen", w), "used_well": _int(p, "used_well", w)}
        )
    for i, p in enumerate(_list(card, "pragmatics")):
        w = f"pragmatics[{i}]"
        _obj(p, {"pattern", "note"}, w)
        out["pragmatics"].append({"pattern": _str(p, "pattern", w), "note": _str(p, "note", w)})
    for i, s in enumerate(_list(card, "interests")):
        if not isinstance(s, str):
            _fail(f"interests[{i}]", "문자열이어야 합니다")
        out["interests"].append(s)
    return out


def enforce_rules(card: Dict[str, Any]) -> Dict[str, Any]:
    """misses >= 3 항목을 fixed_points로 옮기고, weak_points를 정렬·5개로 자른다."""
    weak: List[Dict[str, Any]] = []
    fixed = list(card["fixed_points"])
    fixed_patterns = {p["pattern"] for p in fixed}
    for point in card["weak_points"]:
        if point["misses"] >= MISS_LIMIT:
            moved = {k: v for k, v in point.items() if k != "misses"}
            if moved["pattern"] not in fixed_patterns:
                fixed.append(moved)
                fixed_patterns.add(moved["pattern"])
        else:
            weak.append(point)
    # 횟수 많은 순, 같으면 최근에 본 순
    weak.sort(key=lambda p: (p["count"], p["last_seen"]), reverse=True)
    return {
        **card,
        "weak_points": weak[:MAX_WEAK_POINTS],
        "fixed_points": fixed,
        "thinking_gaps": _sort_gaps(card.get("thinking_gaps") or []),
    }


def load_profile(path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """카드를 읽어 검사한 dict를 돌려준다. 파일이 없으면 None, 깨졌으면 ProfileError."""
    path = Path(path) if path else get_profile_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ProfileError(f"카드를 읽을 수 없습니다 {path}: {e}") from e
    try:
        return validate_profile(json.loads(raw))
    except json.JSONDecodeError as e:
        raise ProfileError(f"카드가 JSON이 아닙니다 {path}: {e}") from e


def _write_atomic(path: Path, card: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(card, ensure_ascii=False, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _backup(path: Path, now: datetime) -> Optional[Path]:
    """기존 카드를 history/<YYYYMMDD-HHMMSS>.json으로 복사한다. 카드가 없으면 None."""
    if not path.exists():
        return None
    directory = get_history_dir(path)
    directory.mkdir(parents=True, exist_ok=True)
    base = now.astimezone(KST).strftime("%Y%m%d-%H%M%S")
    target = directory / f"{base}.json"
    n = 1
    while target.exists():  # 같은 초에 두 번 갱신돼도 덮어쓰지 않는다
        target = directory / f"{base}-{n}.json"
        n += 1
    target.write_bytes(path.read_bytes())
    return target


def parse_model_json(raw: Any) -> Dict[str, Any]:
    """모델 응답(dict 또는 문자열)에서 JSON 객체를 꺼낸다. 코드펜스는 벗긴다."""
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


_CARD_SHAPE = """{
  "updated": "ISO 8601 (copy unchanged)",
  "level": {"cefr": "...", "actfl": "...", "source": "..."},
  "weak_points": [{"pattern": "...", "count": 1, "last_seen": "YYYY-MM-DD", "example": "...", "misses": 0}],
  "fixed_points": [{"pattern": "...", "count": 1, "last_seen": "YYYY-MM-DD", "example": "..."}],
  "phrases": [{"phrase": "...", "first_seen": "YYYY-MM-DD", "used_well": 0}],
  "pragmatics": [{"pattern": "...", "note": "..."}],
  "interests": ["..."],
  "next_goal": "..."
}"""

_PRIVACY_RULE = (
    "PRIVACY: this card is sent to Google on every call. NEVER put personal names, "
    "street or home addresses, phone numbers, emails, or company/employer/school names in it. "
    "Replace them with generic words (\"a coworker\", \"my company\") or leave the item out."
)

_RULES = f"""Rules:
- Return ONLY the full updated card as JSON, exactly this shape (no markdown fences, no commentary, no extra keys):
{_CARD_SHAPE}
- Keep "level" and "updated" exactly as they are; code manages both.
- Leave "thinking_gaps" exactly as it is in the current card (omit it if the card has none); code merges it from the tutoring.
- weak_points: recurring grammar/expression mistakes of the learner, grouped by pattern (e.g. "past tense: I just start -> started"), NOT one row per sentence.
  If a pattern shows up in the new call, add 1 to count, set last_seen to today's date, set misses to 0 and update example with a short real sentence.
  If an existing weak point did NOT show up in the new call, keep it unchanged but add 1 to its misses.
  New patterns start with count 1, misses 0. Keep at most 5 weak_points (drop the least important).
- fixed_points: patterns the learner no longer gets wrong (keep existing ones; do not delete them).
- phrases: useful expressions worth reusing (max 15). Add new ones from the call with first_seen = today; raise used_well by 1 when the learner used one correctly.
- pragmatics: short notes on American workplace register/politeness differences (max 8).
- interests: short topics the learner likes (max 8). next_goal: ONE short sentence for the next call.
- Keep every string short. {_PRIVACY_RULE}"""


def build_update_prompt(card: Dict[str, Any], tutoring: Dict[str, Any], today: str) -> str:
    return (
        "You maintain the learner card of a Korean learner practicing American workplace English.\n"
        f"Today is {today}.\n\n"
        f"{_RULES}\n\n"
        "CURRENT CARD:\n"
        f"{json.dumps(card, ensure_ascii=False, indent=2)}\n\n"
        "NEW CALL TUTORING (analysis of the call that just ended):\n"
        f"{json.dumps({k: v for k, v in tutoring.items() if k != 'friend_message'}, ensure_ascii=False, indent=2)}\n"
    )


def update_profile(
    tutoring: Dict[str, Any],
    *,
    generate_text: Callable[[str], Any],
    path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> bool:
    """튜터링 JSON으로 카드를 갱신한다. 성공하면 True.

    모델 호출·파싱·검사가 실패하면 로그를 남기고 기존 카드에 thinking_gaps만 합쳐 쓴다
    (코드 소유 필드라 모델에 의존하지 않는다). 기존 카드를 읽을 수 없거나 쓰기가 실패하면 False.
    쓰기 전에 기존 카드를 history에 복사하고, 임시 파일 + os.replace로 원자적으로 쓴다.
    """
    path = Path(path) if path else get_profile_path()
    now = now or datetime.now(KST)
    with _UPDATE_LOCK:
        today = now.astimezone(KST).strftime("%Y-%m-%d")
        try:
            old = load_profile(path)
        except Exception as e:  # noqa: BLE001 - 기존 카드를 못 읽으면 건드리지 않는다
            logger.error("학습자 카드 갱신 실패(카드는 그대로): %s", e)
            return False
        old_card = old if old is not None else empty_profile(now)
        # thinking_gaps는 코드 소유: 모델 값은 버리고 통화 분석에서 결정적으로 합친다.
        gaps = merge_thinking_gaps(
            old_card.get("thinking_gaps") or [],
            tutoring.get("thinking_gaps") if isinstance(tutoring, dict) else None,
            today,
        )
        try:
            raw = generate_text(build_update_prompt(old_card, tutoring, today))
            candidate = parse_model_json(raw)
            # level·updated도 코드 소유: 모델이 바꾼 값은 무시한다.
            candidate["level"] = old_card["level"]
            candidate["updated"] = _stamp(now)
            candidate["thinking_gaps"] = gaps
            new_card = enforce_rules(validate_profile(candidate))
        except Exception as e:  # noqa: BLE001 - 모델 쪽 실패여도 생각 방식 기록은 남긴다
            logger.error("학습자 카드 모델 갱신 실패, thinking_gaps만 합쳐 저장: %s", e)
            new_card = enforce_rules({**old_card, "updated": _stamp(now), "thinking_gaps": gaps})
        try:
            _backup(path, now)
            _write_atomic(path, new_card)
        except OSError as e:
            logger.error("학습자 카드 저장 실패 %s: %s", path, e)
            return False
    return True


_INITIAL_RULES = _RULES.replace(
    '- Keep "level" and "updated" exactly as they are; code manages both.\n',
    '- "level": cefr and actfl from the level test result in the material; source like "level-test 2026-10-07". "updated": any ISO string (code overwrites it).\n',
)


def build_initial_card(
    material: str,
    *,
    generate_text: Callable[[str], Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """첫 카드를 자료(튜터링·레벨테스트·학습 기록 텍스트)에서 만든다. 파일은 쓰지 않는다.

    level은 모델이 레벨테스트 결과에서 채운 값을 그대로 둔다. 형식이 틀리면 ProfileError.
    """
    now = now or datetime.now(KST)
    prompt = (
        "You build the FIRST learner card of a Korean learner practicing American workplace English "
        "from the material below.\n"
        f"Today is {now.astimezone(KST).strftime('%Y-%m-%d')}.\n\n"
        f"{_INITIAL_RULES}\n\n"
        "In this first card every weak point starts from what the material shows (count = number of calls/records it appears in, "
        "misses = 0). fixed_points starts empty.\n\n"
        f"MATERIAL:\n{material}\n"
    )
    try:
        candidate = parse_model_json(generate_text(prompt))
    except ValueError as e:  # JSONDecodeError도 ValueError
        raise ProfileError(f"모델 출력이 JSON이 아닙니다: {e}") from e
    candidate["updated"] = _stamp(now)
    candidate["thinking_gaps"] = []  # 코드 소유: 통화 분석에서만 쌓는다
    return enforce_rules(validate_profile(candidate))


def write_profile(card: Dict[str, Any], path: Optional[Path] = None, now: Optional[datetime] = None) -> Path:
    """검사한 카드를 쓴다(기존 카드는 history에 복사). 스크립트용."""
    path = Path(path) if path else get_profile_path()
    now = now or datetime.now(KST)
    card = enforce_rules(validate_profile(card))
    with _UPDATE_LOCK:
        _backup(path, now)
        _write_atomic(path, card)
    return path


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def profile_brief(card: Optional[Dict[str, Any]]) -> str:
    """카드를 짧은 영어 문단(1,200자 이내)으로 바꾼다. 모델을 쓰지 않는다. 비면 ""."""
    if not card:
        return ""
    sections: List[str] = []

    level = card.get("level") or {}
    cefr, actfl = level.get("cefr", ""), level.get("actfl", "")
    if cefr or actfl:
        label = f"{cefr} ({actfl})" if cefr and actfl else (cefr or actfl)
        sections.append(f"Level: {_clip(label, 60)}.")

    weak = (card.get("weak_points") or [])[:MAX_WEAK_POINTS]
    if weak:
        items = []
        for p in weak:
            item = _clip(p.get("pattern", ""), 100)
            example = p.get("example", "")
            if example:
                item += f' (e.g. "{_clip(example, 80)}")'
            items.append(item)
        sections.append("Recurring weak points: " + "; ".join(items) + ".")

    gaps = card.get("thinking_gaps") or []
    if gaps:  # framing 먼저, 각 묶음 안에서는 저장 순서(횟수 순)
        top = sorted(gaps, key=lambda g: g.get("kind") != "framing")[:BRIEF_GAPS]
        items = ", ".join(f"'{_clip(g.get('english', ''), 40)}'" for g in top)
        sections.append(f"{RECYCLE_PREFIX}{items}.")

    goal = card.get("next_goal", "")
    if goal:
        sections.append(f"Next goal: {_clip(goal, 150).rstrip('.')}.")

    phrases = sorted(card.get("phrases") or [], key=lambda p: p.get("used_well", 0))[:6]
    if phrases:
        sections.append("Phrases to reuse: " + ", ".join(_clip(p.get("phrase", ""), 40) for p in phrases) + ".")

    pragmatics = (card.get("pragmatics") or [])[:3]
    if pragmatics:
        sections.append(
            "Pragmatics notes: "
            + "; ".join(_clip(f"{p.get('pattern', '')}: {p.get('note', '')}", 120) for p in pragmatics)
            + "."
        )

    interests = (card.get("interests") or [])[:5]
    if interests:
        sections.append("Interests: " + ", ".join(_clip(i, 30) for i in interests) + ".")

    brief = ""
    for section in sections:  # 앞 구획일수록 중요하다. 넘치는 구획은 건너뛴다.
        candidate = f"{brief} {section}".strip()
        if len(candidate) <= BRIEF_MAX_CHARS:
            brief = candidate
    return brief

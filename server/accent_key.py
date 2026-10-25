"""발음 정답지(accent key): 내 말투 때문에 상대가 잘못 알아듣는 것을 모아 둔 표.

- 습관(habits): 발음 시험의 방향별 결과(어느 소리가 어느 쪽으로 들렸나)에서 읽을 때마다 계산한다.
- 단어(words): 통화 뒤 분석이 찾은 "말투 때문에 잘못 받아쓴 단어"를 PRON_DIR/accent-key.json에 쌓는다.
- 지운 항목(removed)은 시각과 함께 남긴다. 그 뒤에 새로 측정·관찰된 것만 다시 살아난다.
- 통화 지시문(pron.pron_brief)과 통화 뒤 분석(tutor)이 이 정답지를 읽는다.
"""

import copy
import json
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from server import pron

logger = logging.getLogger(__name__)

KEY_FILE = "accent-key.json"
KST = timezone(timedelta(hours=9))

STRONG_RATIO = 0.5
MILD_RATIO = 0.25
MAX_WORDS = 40
MAX_CALLS_PER_WORD = 20
MAX_MISHEARD_PER_CALL = 6
MAX_EXAMPLES = 2
BRIEF_WORDS_MAX_CHARS = 240
KINDS = ("habit", "word")

_lock = threading.RLock()
_WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")
_STEM_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})")


def habit_id(contrast: str, target: str) -> str:
    return f"{contrast}:{target}"


def word_id(heard: str, intended: str) -> str:
    return f"{heard}>{intended}"


def key_path() -> Path:
    return pron.get_pron_dir() / KEY_FILE


def _now() -> datetime:
    return datetime.now(KST)


def _iso(moment: datetime) -> str:
    return moment.astimezone(KST).isoformat(timespec="seconds")


def _parse_iso(text: Any) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(str(text))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=KST)


def stem_time(stem: str) -> Optional[datetime]:
    """전문 파일 이름(YYYY-MM-DD-HHMMSS)의 통화 시각."""
    m = _STEM_RE.fullmatch(stem or "")
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi, s, tzinfo=KST)
    except ValueError:
        return None


# --- 저장 파일 -------------------------------------------------------------


def _empty_stored() -> Dict[str, Any]:
    return {"words": [], "removed": []}


def load_stored() -> Dict[str, Any]:
    """파일에서 단어(words)와 지운 기록(removed)만 읽는다. 없거나 깨졌으면 빈 값."""
    try:
        data = json.loads(key_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _empty_stored()
    except (OSError, ValueError) as e:
        logger.warning("정답지 파일을 읽지 못했어요: %s", e)
        return _empty_stored()
    if not isinstance(data, dict):
        return _empty_stored()
    words = [w for w in data.get("words") or [] if isinstance(w, dict) and w.get("heard") and w.get("intended")]
    removed = [r for r in data.get("removed") or [] if isinstance(r, dict) and r.get("kind") in KINDS and r.get("id")]
    return {"words": words, "removed": removed}


def _save(key: Dict[str, Any]) -> bool:
    path = key_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        pron._write_atomic(path, key)
    except OSError as e:
        logger.error("정답지 저장 실패 %s: %s", path, e)
        return False
    return True


# --- 습관(발음 시험 결과에서 계산) -------------------------------------------


def _strength(as_other: int, total: int) -> str:
    ratio = as_other / max(total, 1)
    if ratio >= STRONG_RATIO:
        return "strong"
    if ratio >= MILD_RATIO:
        return "mild"
    return "slight"


def _action(strength: str) -> str:
    """연습할 발음("practice") | 앱이 알아서 보정만("adjust")."""
    return "practice" if strength in ("strong", "mild") else "adjust"


def _item_text(contrast: str, target: str, heard_text: str = "") -> str:
    """읽은 문장. 들린 글과 낙말이 가장 많이 겹치는 시험 문장을 고른다."""
    heard = set(_words_of(heard_text))
    texts = [i["text"] for i in pron.load_test()["items"] if i["contrast"] == contrast and i["target"] == target]
    return max(texts, key=lambda t: len(heard & set(_words_of(t))), default="")


def _directions_of(contrast: Dict[str, Any]) -> List[Dict[str, Any]]:
    """방향별 숫자. 옛 결과(방향 없음)는 misheard 목록에서 만든다."""
    if contrast.get("directions"):
        return [d for d in contrast["directions"] if d.get("as_other", 0) > 0]
    counts: Dict[str, int] = {}
    for m in contrast.get("misheard") or []:
        counts[m["target"]] = counts.get(m["target"], 0) + 1
    out = []
    for target, n in counts.items():
        pair = pron._pair_of(contrast["contrast"], target)
        if pair:
            out.append({"target": target, "other": pair["other"], "as_other": n, "total": contrast.get("total", n)})
    return out


def habits_from_result(result: Optional[Dict[str, Any]], removed: Iterable[Dict[str, Any]] = ()) -> List[Dict[str, Any]]:
    """시험 결과에서 습관 목록(센 순서). 시험보다 먼저 지운 항목은 빠지고, 시험이 더 새로우면 다시 나온다."""
    if not result:
        return []
    made = _parse_iso(result.get("created_at"))
    gone = {}
    for r in removed:
        if r["kind"] == "habit":
            gone[r["id"]] = _parse_iso(r.get("removed_at"))
    habits = []
    for c in result.get("contrasts") or []:
        for d in _directions_of(c):
            hid = habit_id(c["contrast"], d["target"])
            cut = gone.get(hid)
            if hid in gone and (cut is None or made is None or made <= cut):
                continue
            strength = _strength(d["as_other"], d.get("total", 0))
            heard = [m["heard_text"] for m in c.get("misheard") or [] if m.get("target") == d["target"]]
            habits.append(
                {
                    "id": hid,
                    "contrast": c["contrast"],
                    "label": c.get("label", ""),
                    "meant": d["target"],
                    "heard_as": d["other"],
                    "count": d["as_other"],
                    "total": d.get("total", 0),
                    "strength": strength,
                    "action": _action(strength),
                    "tip": c.get("tip") or pron.TIPS.get(c["contrast"], ""),
                    "examples": [
                        {"meant_text": _item_text(c["contrast"], d["target"], h), "heard_text": h} for h in heard[:MAX_EXAMPLES]
                    ],
                }
            )
    habits.sort(key=lambda h: (h["count"] / max(h["total"], 1), h["count"]), reverse=True)
    return habits


# --- 키 만들기·읽기·쓰기 ------------------------------------------------------


def _compose(result: Optional[Dict[str, Any]], stored: Dict[str, Any]) -> Dict[str, Any]:
    habits = habits_from_result(result, stored["removed"])
    action_of = {h["contrast"]: h["action"] for h in habits}
    words = []
    for w in sorted(stored["words"], key=lambda w: (w.get("count", 0), w.get("last_seen", "")), reverse=True):
        habit = w.get("habit") or ""
        words.append(
            {
                "id": word_id(w["heard"], w["intended"]),
                "heard": w["heard"],
                "intended": w["intended"],
                "count": int(w.get("count", 1)),
                "habit": habit,
                "action": action_of.get(habit.split(":")[0], "adjust"),
                "last_seen": w.get("last_seen", ""),
                "calls": list(w.get("calls") or []),
            }
        )
    return {
        "version": 1,
        "source_date": (result or {}).get("date", ""),
        "habits": habits,
        "words": words,
        "removed": list(stored["removed"]),
    }


def get_key(result: Optional[Dict[str, Any]] = None, *, use_latest: bool = True) -> Dict[str, Any]:
    """지금의 정답지. 파일에 쓰지 않는다(통화 시작 같은 읽기 경로용)."""
    if result is None and use_latest:
        result = pron.latest_result()
    with _lock:
        return _compose(result, load_stored())


def refresh(result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """정답지를 다시 만들어 PRON_DIR/accent-key.json에 저장하고 돌려준다. 내용이 같으면 파일을 다시 쓰지 않는다."""
    if result is None:
        result = pron.latest_result()
    with _lock:
        key = _compose(result, load_stored())
        try:
            old = json.loads(key_path().read_text(encoding="utf-8"))
            old.pop("updated_at", None)
        except (OSError, ValueError):
            old = None
        if old != key:
            _save({**key, "updated_at": _iso(_now())})
        return key


def public_key(key: Dict[str, Any]) -> Dict[str, Any]:
    """화면에 보내는 모양(지운 기록은 뺀다)."""
    return {k: v for k, v in key.items() if k != "removed"}


def remove(kind: Any, entry_id: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """틀린 항목 하나를 지운다. kind가 틀리면 ValueError, 그런 항목이 없으면 KeyError."""
    if kind not in KINDS or not isinstance(entry_id, str) or not entry_id:
        raise ValueError("지울 항목을 알 수 없어요.")
    moment = now or _now()
    with _lock:
        stored = load_stored()
        result = pron.latest_result()
        key = _compose(result, stored)
        if kind == "habit":
            if entry_id not in {h["id"] for h in key["habits"]}:
                raise KeyError(entry_id)
        else:
            if entry_id not in {w["id"] for w in key["words"]}:
                raise KeyError(entry_id)
            stored["words"] = [w for w in stored["words"] if word_id(w["heard"], w["intended"]) != entry_id]
        stored["removed"] = [r for r in stored["removed"] if not (r["kind"] == kind and r["id"] == entry_id)]
        stored["removed"].append({"kind": kind, "id": entry_id, "removed_at": _iso(moment)})
        key = _compose(result, stored)
        _save({**key, "updated_at": _iso(moment)})
        return key


# --- 통화 뒤 분석: 오인식 단어 ------------------------------------------------

_ANALYSIS_SECTION = """

ACCENT KEY (this learner's accent makes the live speech recognizer hear some sounds as other words; the "Me:" lines are what it heard):
{lines}
Also add one more key to the JSON, "accent_misheard": [{{"heard": "boat", "intended": "vote", "habit": "b_v:vote"}}]. List up to {max_items} words in the "Me:" lines where the recognizer most likely misheard the learner because of one of the habits above: "heard" is the word as written in a Me line, "intended" is the word the learner almost certainly meant (judge it from the conversation), and "habit" is the id (the part in brackets) of the habit that explains the swap. Only list a word when the heard word does not fit the sentence but the intended word does. If nothing fits, use an empty list.
A word you list in accent_misheard is NOT the learner's mistake. Do not put a sentence in "corrections" when the only problem is that swapped word, and do not use it for vocab, us_style or thinking_gaps."""


def analysis_section(key: Optional[Dict[str, Any]]) -> str:
    """분석 프롬프트 끝에 붙일 정답지 구간. 습관이 없으면 빈 글(분석은 예전과 같다)."""
    habits = (key or {}).get("habits") or []
    if not habits:
        return ""
    lines = "\n".join(
        f"- [{h['id']}] {h['label']}: the learner means \"{h['meant']}\" but it is heard as \"{h['heard_as']}\" ({h['count']} of {h['total']} test sentences)"
        for h in habits[:8]
    )
    return _ANALYSIS_SECTION.format(lines=lines, max_items=MAX_MISHEARD_PER_CALL)


def normalize_misheard(raw: Any, learner_tokens: Iterable[str], key: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """모델이 낸 accent_misheard를 걸러 낸다. 습관 id가 정답지에 있고, 들린 단어가 학습자 줄에 실제로 있어야 한다."""
    habits = {h["id"]: h for h in (key or {}).get("habits") or []}
    if not habits or not isinstance(raw, list):
        return []
    spoken = set(learner_tokens)
    out: List[Dict[str, str]] = []
    seen = set()
    for row in raw:
        if not isinstance(row, dict):
            continue
        heard = str(row.get("heard") or "").strip().lower().replace("’", "'")
        intended = str(row.get("intended") or "").strip().lower().replace("’", "'")
        hid = str(row.get("habit") or "").strip()
        if not (_WORD_RE.fullmatch(heard) and _WORD_RE.fullmatch(intended)) or heard == intended:
            continue
        if hid not in habits or heard not in spoken or (heard, intended) in seen:
            continue
        seen.add((heard, intended))
        out.append({"heard": heard, "intended": intended, "habit": hid})
        if len(out) >= MAX_MISHEARD_PER_CALL:
            break
    return out


def _words_of(text: str) -> List[str]:
    return _WORD_RE.findall((text or "").lower().replace("’", "'"))


def drop_explained(corrections: List[Dict[str, str]], pairs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """정답지로 설명되는 오인식 하나만 고친 교정은 뺀다.

    said의 heard를 intended로 바꾸면 better와 낱말 집합이 같아지는 경우다(문법·단어 고침이 더 있으면 남긴다).
    """
    if not pairs:
        return corrections
    swap = {p["heard"]: p["intended"] for p in pairs}
    kept = []
    for row in corrections:
        said = _words_of(row.get("said", ""))
        if any(w in swap for w in said):
            fixed = {swap.get(w, w) for w in said}
            if fixed == set(_words_of(row.get("better", ""))):
                continue
        kept.append(row)
    return kept


def merge_call_words(stem: str, pairs: Optional[List[Dict[str, str]]], now: Optional[datetime] = None) -> int:
    """통화 하나에서 찾은 오인식 단어를 정답지 파일에 합친다. 같은 통화를 다시 분석해도 두 번 세지 않는다. 합친 개수를 돌려준다."""
    if not pairs:
        return 0
    moment = now or _now()
    called = stem_time(stem)
    merged = 0
    with _lock:
        stored = load_stored()
        gone = {r["id"]: _parse_iso(r.get("removed_at")) for r in stored["removed"] if r["kind"] == "word"}
        by_id = {word_id(w["heard"], w["intended"]): w for w in stored["words"]}
        for p in pairs:
            wid = word_id(p["heard"], p["intended"])
            if wid in gone:
                cut = gone[wid]
                if cut is None or called is None or called <= cut:
                    continue
                stored["removed"] = [r for r in stored["removed"] if not (r["kind"] == "word" and r["id"] == wid)]
                gone.pop(wid)
            entry = by_id.get(wid)
            if entry is None:
                entry = {"heard": p["heard"], "intended": p["intended"], "habit": p.get("habit", ""), "count": 0, "calls": []}
                by_id[wid] = entry
                stored["words"].append(entry)
            if stem in entry["calls"]:
                continue
            entry["calls"] = (entry["calls"] + [stem])[-MAX_CALLS_PER_WORD:]
            entry["count"] = int(entry.get("count", 0)) + 1
            entry["last_seen"] = _iso(called or moment)
            if p.get("habit"):
                entry["habit"] = p["habit"]
            merged += 1
        if merged:
            stored["words"].sort(key=lambda w: (w.get("count", 0), w.get("last_seen", "")), reverse=True)
            stored["words"] = stored["words"][:MAX_WORDS]
            key = _compose(pron.latest_result(), stored)
            _save({**key, "updated_at": _iso(moment)})
    return merged


# --- 통화 지시문 --------------------------------------------------------------


def without_removed(result: Optional[Dict[str, Any]], key: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """지운 습관을 시험 결과에서 빼 낸 사본(통화 지시문이 지운 것을 다시 말하지 않게)."""
    if not result:
        return result
    live = {h["id"] for h in key.get("habits") or []}
    out = copy.deepcopy(result)
    for c in out.get("contrasts") or []:
        for d in c.get("directions") or []:
            if d.get("as_other", 0) > 0 and habit_id(c["contrast"], d["target"]) not in live:
                c["as_other"] -= d["as_other"]
                d["as_other"] = 0
                c["misheard"] = [m for m in c.get("misheard") or [] if m.get("target") != d["target"]]
        if not c.get("directions"):
            for target in {m["target"] for m in c.get("misheard") or []}:
                if habit_id(c["contrast"], target) not in live:
                    c["as_other"] -= sum(1 for m in c["misheard"] if m["target"] == target)
                    c["misheard"] = [m for m in c["misheard"] if m["target"] != target]
    return out


def words_brief(key: Optional[Dict[str, Any]]) -> str:
    """통화에서 모은 오인식 단어 한 줄(영어). 없으면 빈 글."""
    words = (key or {}).get("words") or []
    if not words:
        return ""
    head = "Words the learner meant that were heard as other words in earlier calls because of the accent (meant -> heard): "
    pieces = []
    for w in words:
        piece = f"{w['intended']} -> {w['heard']}"
        if len(head) + len("; ".join(pieces + [piece])) > BRIEF_WORDS_MAX_CHARS:
            break
        pieces.append(piece)
    return head + "; ".join(pieces) + "." if pieces else ""

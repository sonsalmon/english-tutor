"""발음 시험: 짝(minimal pair) 문장을 읽게 하고, 서버가 정답을 모른 채 받아쓴 글로 어느 쪽 단어로 들렸는지 가린다.

- 시험 문항은 server/pron_test.json. 화면에는 id와 문장만 보내고 target·other는 숨긴다.
- 받아쓰기(transcribe_wav)는 문항을 모르는 전용 프롬프트로 Vertex를 한 번 부른다. 테스트에서는 이 함수를 바꿔 끼운다.
- 판정(judge_item)은 받아쓴 글에서 짝의 두 단어 중 무엇이 있는지만 본다.
- 결과는 PRON_DIR(기본 ~/dev/learning/english/pronunciation)에 YYYY-MM-DD-HHMMSS.json으로 저장한다.
"""

import json
import logging
import os
import random
import re
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from server import pricing

logger = logging.getLogger(__name__)

PRON_DIR_ENV = "PRON_DIR"
DEFAULT_PRON_DIR = "~/dev/learning/english/pronunciation"
TEST_FILE = Path(__file__).resolve().parent / "pron_test.json"
KST = timezone(timedelta(hours=9))

MAX_WAV_BYTES = 2 * 1024 * 1024
MAX_ANSWERS = 40
MAX_ANSWER_CHARS = 500
BRIEF_MAX_CHARS = 600
RESULT_FILE_RE = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}\.json", re.ASCII)

BLIND_PROMPT = (
    "Transcribe exactly what you hear in this recording of ONE English sentence read aloud by a learner. "
    "Write the words as they sound. Do NOT fix grammar. Do NOT guess a word from meaning or context: "
    "if you did not clearly hear it, write the closest sounding word. Keep fillers (um, uh) and repetitions. "
    "If one word is acoustically ambiguous between two similar-sounding words, write it as [a/b?], "
    "for example [can/can't?]. Output plain text on one line, with no quotes and no commentary."
)

TIPS: Dict[str, str] = {
    "can_cant": (
        "can은 [kən]처럼 약하고 짧게, can't는 [kænt]처럼 모음을 길고 크게 말해요. "
        "can't는 끝의 t를 소리 내지 않고 혀끝으로 막기만 해도 돼요. "
        "문장 끝의 can't도 모음을 길게 끌어 주면 구분돼요."
    ),
    "l_r": (
        "l은 혀끝을 윗잇몸 뒤에 붙이고 소리 내요. "
        "r은 혀끝을 어디에도 닿지 않게 뒤로 말고 입술을 살짝 모아요. "
        "collect와 correct는 세 번째 글자(l / r) 소리에서 혀 위치를 바꿔 보세요."
    ),
    "p_f": (
        "p는 두 입술을 붙였다가 공기를 터뜨려요. "
        "f는 윗니를 아랫입술에 가볍게 대고 공기를 계속 내보내요. "
        "손바닥을 입 앞에 대고 p에서는 공기가 톡 터지는지 확인해 보세요."
    ),
    "b_v": (
        "b는 두 입술을 붙였다가 떼면서 소리 내요. "
        "v는 윗니를 아랫입술에 대고 성대를 울리며 공기를 계속 내보내요. "
        "vote에서는 입술이 아니라 이가 아랫입술에 닿는지 거울로 확인해 보세요."
    ),
    "th_f": (
        "th는 혀끝을 윗니와 아랫니 사이에 살짝 내밀고 공기를 내보내요. "
        "f는 혀를 쓰지 않고 윗니를 아랫입술에 대요. "
        "three를 말할 때 혀끝이 이 사이에서 살짝 보이는지 확인해 보세요."
    ),
    "i_ee": (
        "짧은 i는 입을 많이 벌리지 않고 힘을 빼서 짧게 말해요(ship, live). "
        "긴 ee는 입꼬리를 옆으로 당기고 길게 늘여요(sheep, leave). "
        "길이만이 아니라 입 모양도 함께 바꿔야 해요."
    ),
    "ed": (
        "-ed는 앞소리에 따라 /t/, /d/, /ɪd/ 중 하나로 소리 나요. "
        "walked처럼 무성음 뒤에서는 /t/를 끝에 분명히 붙이고, 끝소리를 생략하지 마세요. "
        "과거 이야기에서는 walk로 끝내지 않도록 마지막 t를 살짝 터뜨려 보세요."
    ),
}

_FILLER_TIP = "이 소리는 짝이 되는 소리와 입 모양이 어떻게 다른지 확인하며 천천히 연습해 보세요."

_TOKEN_RE = re.compile(r"[a-z]+(?:'[a-z]+)*")
_BRACKET_RE = re.compile(r"\[([^\[\]]*?)\??\]")
_CANT_FORMS = {"can't", "cant", "cannot"}

_lock = threading.Lock()
_session_usage = pricing.UsageTotals()


def load_test() -> Dict[str, Any]:
    with TEST_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def build_test() -> Dict[str, Any]:
    """화면용 시험: 문항은 섞고 id와 문장만 준다(target·other·contrast는 숨긴다)."""
    data = load_test()
    items = [{"id": i["id"], "text": i["text"]} for i in data["items"]]
    random.shuffle(items)
    return {"items": items, "contrasts": dict(data["contrasts"])}


def _norm(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'").lower()


def _tokens(text: str) -> List[str]:
    cleaned = re.sub(r"\bcan not\b", "cannot", _norm(text))
    return _TOKEN_RE.findall(cleaned)


def _present(word: str, tokens: List[str]) -> bool:
    word = _norm(word)
    if word == "can't":
        return any(t in _CANT_FORMS for t in tokens)
    if word == "can":
        return "can" in tokens and not any(t in _CANT_FORMS for t in tokens)
    return word in tokens


def _bracket_has_pair(text: str, target: str, other: str) -> bool:
    for body in _BRACKET_RE.findall(_norm(text)):
        alternatives = [_tokens(part) for part in body.split("/")]
        if any(_present(target, a) for a in alternatives) and any(_present(other, a) for a in alternatives):
            return True
    return False


def judge_item(item: Dict[str, Any], heard_text: str) -> str:
    """받아쓴 글에서 짝의 어느 쪽이 들렸는지: "target" | "other" | "unclear"."""
    target, other = item["target"], item["other"]
    if _bracket_has_pair(heard_text, target, other):
        return "unclear"
    tokens = _tokens(heard_text)
    has_target, has_other = _present(target, tokens), _present(other, tokens)
    if has_target == has_other:
        return "unclear"
    return "target" if has_target else "other"


def judge_answers(answers: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """답(id, text)마다 판정해 대비(contrast)별로 모은다. 시험의 모든 대비를 시험 순서대로 돌려준다."""
    data = load_test()
    by_id = {i["id"]: i for i in data["items"]}
    rows: Dict[str, Dict[str, Any]] = {
        key: {
            "contrast": key,
            "label": label,
            "total": 0,
            "as_target": 0,
            "as_other": 0,
            "unclear": 0,
            "misheard": [],
            "unclear_heard": [],
            "tip": TIPS.get(key, _FILLER_TIP),
            "directions": [],
        }
        for key, label in data["contrasts"].items()
    }
    directions: Dict[Any, Dict[str, Any]] = {}
    for item in data["items"]:
        key = (item["contrast"], item["target"])
        if key not in directions:
            directions[key] = {"target": item["target"], "other": item["other"], "total": 0, "as_target": 0, "as_other": 0, "unclear": 0}
            rows[item["contrast"]]["directions"].append(directions[key])
    for answer in answers:
        item = by_id[answer["id"]]
        row = rows[item["contrast"]]
        verdict = judge_item(item, answer["text"])
        direction = directions[(item["contrast"], item["target"])]
        direction["total"] += 1
        direction["as_" + verdict if verdict != "unclear" else "unclear"] += 1
        row["total"] += 1
        row["as_" + verdict if verdict != "unclear" else "unclear"] += 1
        if verdict == "other":
            row["misheard"].append({"target": item["target"], "heard_text": answer["text"]})
        elif verdict == "unclear":
            row["unclear_heard"].append({"target": item["target"], "heard_text": answer["text"]})
    return list(rows.values())


def _pair_of(contrast: str, target: Optional[str] = None) -> Optional[Dict[str, Any]]:
    for item in load_test()["items"]:
        if item["contrast"] == contrast and (target is None or item["target"] == target):
            return item
    return None


def weak_contrasts(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    weak = [c for c in result.get("contrasts") or [] if c.get("as_other", 0) + c.get("unclear", 0) >= 1]
    weak.sort(key=lambda c: (c["as_other"] + c["unclear"]) / max(c["total"], 1), reverse=True)
    return weak


def pron_brief(result: Optional[Dict[str, Any]]) -> str:
    """통화 지시문에 붙일 영어 두 줄(약한 대비가 최대 3개). 약한 대비가 없으면 빈 글."""
    if not result:
        return ""
    weak = weak_contrasts(result)[:3]
    if not weak:
        return ""
    parts = []
    for c in weak:
        total = c["total"]
        pieces = []
        if c.get("directions"):
            for d in [d for d in c["directions"] if d.get("as_other", 0) > 0][:2]:
                pieces.append(f"{d['target']} was heard as {d['other']} in {d['as_other']} of {d['total']} sentences")
        else:
            counts: Dict[str, int] = {}
            for m in c.get("misheard") or []:
                counts[m["target"]] = counts.get(m["target"], 0) + 1
            for target, n in list(counts.items())[:2]:
                pair = _pair_of(c["contrast"], target)
                if pair:
                    pieces.append(f"{target} was heard as {pair['other']} in {n} of {total} sentences")
        if c["unclear"]:
            pieces.append(f"could not tell in {c['unclear']} of {total} sentences")
        parts.append(f"{c['label']}: " + ", ".join(pieces))
    first = weak[0]
    misheard = (first.get("misheard") or [{}])[0].get("target")
    pair = _pair_of(first["contrast"], misheard)
    question = ""
    if pair:
        words = sorted([pair["target"], pair["other"]])
        question = f" e.g. 'Did you mean {words[0]} or {words[1]}?'"
    head = f"Pronunciation check (reading test {result.get('date', '')}): "
    tail = ".\nWhen you are not sure which of these words the learner said, ask briefly," + (question or " by naming the two words.")
    while len(parts) > 1 and len(head) + len("; ".join(parts)) + len(tail) > BRIEF_MAX_CHARS:
        parts.pop()
    return head + "; ".join(parts) + tail


def _worst_direction(contrast: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    for d in contrast.get("directions") or []:
        if d.get("total", 0) <= 0:
            continue
        if best is None or (d["as_other"] + d["unclear"]) / d["total"] > (best["as_other"] + best["unclear"]) / best["total"]:
            best = d
    if best is None:
        return None
    return {k: best[k] for k in ("target", "other", "as_other", "unclear", "total")}


def weak_summary(result: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """GET /api/learner-profile의 "pron" 값. 시험 결과가 없으면 None."""
    if not result:
        return None
    weak = []
    for c in weak_contrasts(result):
        entry = {"label": c["label"], "as_other": c["as_other"], "unclear": c["unclear"], "total": c["total"]}
        if c.get("directions"):  # 옛 저장 결과에는 방향이 없으니 키를 넣지 않는다
            entry["worst"] = _worst_direction(c)
        weak.append(entry)
    return {"date": result.get("date", ""), "weak": weak}


def get_pron_dir() -> Path:
    return Path(os.path.expanduser(os.getenv(PRON_DIR_ENV) or DEFAULT_PRON_DIR))


def _clean_line(text: Any) -> str:
    return " ".join(str(text or "").split())


def transcribe_wav(wav_bytes: bytes) -> str:
    """문장 하나를 정답 모르게 받아쓴다(Vertex, TUTOR_MODEL). 테스트에서는 이 함수를 바꿔 끼운다."""
    from google.genai import types

    from server import tutor

    client = tutor._make_client()
    model = tutor.tutor_model()
    response = client.models.generate_content(
        model=model,
        contents=[types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav"), BLIND_PROMPT],
        config=types.GenerateContentConfig(temperature=0.0, thinking_config=types.ThinkingConfig(thinking_budget=0)),
    )
    add_session_usage(response)
    return _clean_line(response.text)


def add_session_usage(response: Any) -> None:
    with _lock:
        _session_usage.add_metadata(getattr(response, "usage_metadata", None))


def _take_session_cost(model: str) -> Optional[float]:
    global _session_usage
    with _lock:
        usage, _session_usage = _session_usage, pricing.UsageTotals()
    return None if usage.is_empty() else usage.cost(model)


def validate_answers(body: Any) -> List[Dict[str, str]]:
    """{"answers":[{"id","text"}]} 검사. 틀리면 ValueError(한국어 메시지)."""
    raw = body.get("answers") if isinstance(body, dict) else None
    if not isinstance(raw, list) or not raw:
        raise ValueError("답이 비었어요.")
    if len(raw) > MAX_ANSWERS:
        raise ValueError(f"답은 {MAX_ANSWERS}개까지 보낼 수 있어요.")
    known = {i["id"] for i in load_test()["items"]}
    by_id: Dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or not isinstance(entry.get("text"), str):
            raise ValueError("답의 형식이 틀렸어요.")
        if entry["id"] not in known:
            raise ValueError("모르는 문항 번호예요.")
        if len(entry["text"]) > MAX_ANSWER_CHARS:
            raise ValueError("받아쓴 글이 너무 길어요.")
        by_id[entry["id"]] = _clean_line(entry["text"])
    return [{"id": k, "text": v} for k, v in by_id.items()]


def finish(answers: List[Dict[str, str]], now: Optional[datetime] = None, model: Optional[str] = None) -> Dict[str, Any]:
    """판정·집계해서 PRON_DIR에 저장하고 결과를 돌려준다. 저장이 실패해도 결과는 돌려준다."""
    now = (now or datetime.now(KST)).astimezone(KST)
    result: Dict[str, Any] = {
        "date": now.strftime("%Y-%m-%d"),
        "created_at": now.isoformat(timespec="seconds"),
        "contrasts": judge_answers(answers),
        "cost_usd": _take_session_cost(model or os.getenv("TUTOR_MODEL", pricing.TUTOR_MODEL)),
    }
    directory = get_pron_dir()
    path = directory / (now.strftime("%Y-%m-%d-%H%M%S") + ".json")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _write_atomic(path, result)
    except OSError as e:
        logger.error("발음 시험 결과 저장 실패 %s: %s", path, e)
    return result


def _write_atomic(path: Path, data: Dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def latest_result() -> Optional[Dict[str, Any]]:
    """가장 최근 시험 결과. 없거나 읽을 수 없으면 None."""
    directory = get_pron_dir()
    try:
        names = sorted((p.name for p in directory.glob("*.json") if RESULT_FILE_RE.fullmatch(p.name)), reverse=True)
    except OSError:
        return None
    for name in names:
        try:
            data = json.loads((directory / name).read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            logger.warning("발음 시험 결과를 읽지 못했어요 %s: %s", name, e)
            continue
        if isinstance(data, dict) and isinstance(data.get("contrasts"), list):
            return data
    return None

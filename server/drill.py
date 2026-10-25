"""문법 미니 드릴: 학습자 카드의 약점(weak_points)으로 하루에 한 번 5문제를 만든다.

- 문제는 Vertex 텍스트 모델(tutor와 같은 클라이언트·모델)이 JSON으로 만든다. 테스트에서는 generate를 바꿔 끼운다.
- 하루(KST) 한 벌을 DRILL_DIR/drill-YYYY-MM-DD.json에 저장한다. 같은 날 다시 열면 모델을 부르지 않는다.
- 정답과 해설은 서버만 들고 있다. 화면에는 문제만 보내고(public), 답은 check_answer로 판정한다.
"""

import json
import logging
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from server.learner_profile import KST, MAX_WEAK_POINTS, get_profile_path, load_profile

logger = logging.getLogger(__name__)

DRILL_DIR_ENV = "DRILL_DIR"
QUESTION_COUNT = 5
TYPES = ("blank", "choice", "rephrase")
BLANK = "____"
MAX_PROMPT_CHARS = 240
MAX_EXPLAIN_CHARS = 300
MAX_ANSWER_CHARS = 300
MAX_ATTEMPTS = 2
REQUEST_TIMEOUT_MS = 40_000
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)

_LOCK = threading.Lock()


class DrillError(Exception):
    """문제를 만들거나 읽지 못했을 때."""


class NoWeakPoints(DrillError):
    """학습자 카드에 약점이 아직 없을 때(모델을 부르지 않는다)."""


def today(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(KST)).astimezone(KST).strftime("%Y-%m-%d")


def get_drill_dir() -> Path:
    configured = os.getenv(DRILL_DIR_ENV)
    return Path(os.path.expanduser(configured)) if configured else get_profile_path().parent / "drills"


def _path_for(date: str) -> Path:
    if not _DATE_RE.fullmatch(date):
        raise ValueError("날짜 형식이 틀렸어요.")
    return get_drill_dir() / f"drill-{date}.json"


PROMPT = """You write a 5-question grammar mini drill for an adult Korean learner of American English (workplace and daily life).
The drill must practice the learner's current weak points:
{weak}

Rules:
- Exactly {count} questions: 2 of type "blank", 2 of type "choice", 1 of type "rephrase". Cover as many different weak points as you can; each question targets one of them (copy its pattern text into "focus").
- Natural American English, one short sentence per question (at most 18 words). Do not reuse the learner's example sentences verbatim.
- "blank": "prompt" is a sentence with exactly one blank written as ____ . "answer" is the 1-3 words that fill it. "accept" lists other fully correct fillers (may be empty).
- "choice": "prompt" is a sentence with exactly one ____ . "options" has 3 options, only one is correct, and "answer" is that option written exactly as in "options". Wrong options must be clearly wrong in this sentence, never just less common (avoid pairs like at/in the office where both sound natural).
- "rephrase": "prompt" is a sentence that contains the learner's kind of mistake. The learner rewrites it correctly. "answer" is the best rewrite and "accept" lists 1-3 other correct rewrites that keep exactly the same meaning and fix only the mistake.
- "explanation_ko": at most 2 short sentences in plain Korean saying why the answer is right and what the mistake is. No jargon.
- Questions must have exactly one defensible answer (plus the "accept" list).

Return only JSON: {{"questions":[{{"type":"blank|choice|rephrase","focus":"...","prompt":"...","options":["..."],"answer":"...","accept":["..."],"explanation_ko":"..."}}]}}"""


def build_prompt(weak_points: List[Dict[str, Any]]) -> str:
    lines = []
    for point in weak_points[:MAX_WEAK_POINTS]:
        line = f"- {point['pattern']}"
        if point.get("example"):
            line += f' (learner said: "{point["example"]}")'
        lines.append(line)
    return PROMPT.format(weak="\n".join(lines), count=QUESTION_COUNT)


def _text(value: Any, where: str, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{where}: 문자열이어야 합니다")
    text = " ".join(value.split())
    if (not text and not allow_empty) or len(text) > limit:
        raise ValueError(f"{where}: 비었거나 너무 깁니다")
    return text


def _str_list(value: Any, where: str, limit: int) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{where}: 배열이어야 합니다")
    return [_text(v, where, limit) for v in value]


def _question(raw: Any, index: int) -> Dict[str, Any]:
    where = f"questions[{index}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: 객체여야 합니다")
    kind = raw.get("type")
    if kind not in TYPES:
        raise ValueError(f"{where}: type이 {TYPES} 중 하나여야 합니다")
    prompt = _text(raw.get("prompt"), f"{where}.prompt", MAX_PROMPT_CHARS)
    answer = _text(raw.get("answer"), f"{where}.answer", MAX_ANSWER_CHARS)
    out: Dict[str, Any] = {
        "id": f"q{index + 1}",
        "type": kind,
        "focus": _text(raw.get("focus", ""), f"{where}.focus", MAX_PROMPT_CHARS, allow_empty=True),
        "answer": answer,
        "explanation": _text(raw.get("explanation_ko"), f"{where}.explanation_ko", MAX_EXPLAIN_CHARS),
    }
    if kind in ("blank", "choice"):
        prompt = re.sub(r"_{2,}", BLANK, prompt)
        if prompt.count(BLANK) != 1:
            raise ValueError(f"{where}.prompt: 빈칸(____)이 정확히 하나여야 합니다")
    out["prompt"] = prompt
    accept = _str_list(raw.get("accept"), f"{where}.accept", MAX_ANSWER_CHARS)
    if kind == "choice":
        options = _str_list(raw.get("options"), f"{where}.options", MAX_ANSWER_CHARS)
        if len(options) < 3 or len(options) > 4 or len({_norm(o) for o in options}) != len(options):
            raise ValueError(f"{where}.options: 서로 다른 보기 3~4개여야 합니다")
        matched = [o for o in options if _norm(o) == _norm(answer)]
        if not matched:
            raise ValueError(f"{where}.answer: 보기 안에 있어야 합니다")
        out["options"] = options
        out["answer"] = matched[0]
        accept = []
    out["accept"] = accept[:5]
    return out


def validate_questions(raw: Any) -> List[Dict[str, Any]]:
    """모델 JSON({"questions":[...]})을 검사해 저장 형식으로 돌려준다. 틀리면 ValueError."""
    items = raw.get("questions") if isinstance(raw, dict) else None
    if not isinstance(items, list) or len(items) != QUESTION_COUNT:
        raise ValueError(f"questions는 {QUESTION_COUNT}개여야 합니다")
    return [_question(item, i) for i, item in enumerate(items)]


def default_generate(prompt: str) -> str:
    """Vertex 텍스트 모델로 JSON 문제 묶음을 만든다. 테스트에서는 이 함수를 바꿔 끼운다."""
    from google.genai import types

    from server import tutor

    client = tutor._make_client(http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
    model = tutor.tutor_model()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.7,
        thinking_config=types.ThinkingConfig(thinking_budget=0) if "flash" in model else None,
    )
    response = client.models.generate_content(model=model, contents=prompt, config=config)
    tutor.record_usage(response)
    return response.text or ""


def _read(date: str) -> Optional[Dict[str, Any]]:
    path = _path_for(date)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        questions = validate_questions({"questions": [_stored_to_raw(q) for q in data["questions"]]})
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        logger.warning(f"Drill cache unreadable, regenerating {path}: {e}")
        return None
    return {"date": date, "questions": questions}


def _stored_to_raw(q: Dict[str, Any]) -> Dict[str, Any]:
    return {**q, "explanation_ko": q.get("explanation")}


def _write(drill: Dict[str, Any]) -> None:
    path = _path_for(drill["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(drill, ensure_ascii=False, indent=2) + "\n")
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def get_drill(now: Optional[datetime] = None, generate: Optional[Callable[[str], str]] = None) -> Dict[str, Any]:
    """오늘의 드릴. 저장본이 있으면 그대로(cached=True), 없으면 약점으로 만들어 저장한다.

    약점이 없으면 NoWeakPoints, 모델이 두 번 모두 못 만들면 DrillError. 동시에 열어도 한 번만 만든다.
    """
    date = today(now)
    with _LOCK:
        stored = _read(date)
        if stored:
            return {**stored, "cached": True}
        card = load_profile()
        weak = list(card["weak_points"]) if card else []
        if not weak:
            raise NoWeakPoints("학습자 카드에 약점이 없습니다")
        prompt = build_prompt(weak)
        last: Optional[Exception] = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                text = (generate or default_generate)(prompt)
                questions = validate_questions(json.loads(text))
            except (ValueError, TypeError) as e:
                logger.warning(f"Drill generation attempt {attempt + 1} invalid: {e}")
                last = e
                continue
            drill = {"date": date, "questions": questions}
            _write(drill)
            return {**drill, "cached": False}
        raise DrillError(f"문제를 만들지 못했습니다: {last}")


def public(drill: Dict[str, Any]) -> Dict[str, Any]:
    """화면에 보내는 형식: 정답·인정 답·해설은 뺀다."""
    questions = []
    for q in drill["questions"]:
        item = {"id": q["id"], "type": q["type"], "focus": q["focus"], "prompt": q["prompt"]}
        if q["type"] == "choice":
            item["options"] = q["options"]
        questions.append(item)
    return {"date": drill["date"], "cached": bool(drill.get("cached")), "questions": questions}


def _norm(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').lower()
    text = re.sub(r"[.,!?;:\"]", " ", text)
    return " ".join(text.split())


def _is_correct(q: Dict[str, Any], given: str) -> bool:
    got = _norm(given)
    if not got:
        return False
    answers = [q["answer"], *q.get("accept", [])]
    if got in {_norm(a) for a in answers}:
        return True
    if q["type"] == "blank":
        # 빈칸을 채운 문장 전체를 쓴 경우도 맞게 본다.
        return got in {_norm(q["prompt"].replace(BLANK, a)) for a in answers}
    return False


def check_answer(date: str, question_id: str, answer: Any) -> Dict[str, Any]:
    """저장된 드릴에서 한 문제를 판정한다. 없으면 LookupError, 답 형식이 틀리면 ValueError."""
    if not isinstance(answer, str) or len(answer) > MAX_ANSWER_CHARS:
        raise ValueError("답은 300자 이하의 글이어야 해요.")
    drill = _read(date)
    if drill is None:
        raise LookupError("그날의 문제가 없어요.")
    q = next((q for q in drill["questions"] if q["id"] == question_id), None)
    if q is None:
        raise LookupError("없는 문제예요.")
    correct = _is_correct(q, answer)
    return {
        "id": q["id"],
        "correct": correct,
        "answer": q["answer"],
        "explanation": q["explanation"],
        # 바꿔 쓰기는 뜻이 같은 다른 답도 많아서, 틀림으로 나와도 예시 답과 비교하게 안내한다.
        "loose": q["type"] == "rephrase" and not correct,
    }

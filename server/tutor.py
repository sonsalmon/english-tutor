# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""통화 전문(마크다운)을 Vertex AI 텍스트 모델로 분석해 튜터링 JSON을 만든다.

새 API 키를 쓰지 않는다. 기존 `.env`의 PROJECT_ID·LOCATION과 ADC(구글 클라우드
로그인)로 Vertex AI의 텍스트 모델을 부른다. 모델이 JSON만 내도록 시키고, 파싱에
실패하면 한 번 재시도한다. 결과는 `~/dev/learning/english/tutoring/<같은 파일명>.json`
에 저장한다(경로 규칙은 transcript_store.py의 helper를 그대로 쓴다).
"""

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from google import genai
from google.genai import types

from server.config_utils import get_project_id
from server.transcript_store import (
    get_audio_dir,
    get_teachback_dir,
    get_transcript_dir,
    get_tutoring_dir,
)

logger = logging.getLogger(__name__)

# 텍스트 분석 모델. Live 음성 모델(MODEL)과 별개다.
TUTOR_MODEL_ENV = "TUTOR_MODEL"
DEFAULT_TUTOR_MODEL = "gemini-2.5-flash"

# sessions/ 안에서만 인정하는 파일명 형식(경로 주입 방지).
# re.fullmatch로 쓰고 re.ASCII를 켜서 줄바꿈(끝의 $가 삼키던)과 비ASCII 숫자를 거부한다.
FILENAME_RE = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}\.md", re.ASCII)


class TutoringAnalysisError(RuntimeError):
    """분석 결과가 비었거나(5개 섹션 모두 빔) 파싱에 두 번 실패한 경우."""


MAX_CORRECTIONS = 5
MAX_GOOD = 3
MAX_VOCAB = 6
MAX_PRAGMATICS = 4
MAX_PHRASES = 4
MAX_UNANSWERED = 8

# teach-back에서 "답하지 못한 질문"의 원인. 계약상 이 넷 중 하나로 고정한다.
CAUSES = ("english", "understanding", "both", "unclear")

_CONTRACT_HINT = """{
  "corrections": [{"said": "...", "better": "...", "why": "한국어 한두 문장"}],
  "good": [{"said": "...", "note": "왜 좋았는지 한 줄"}],
  "vocab": [{"word": "...", "meaning_ko": "...", "example": "...", "etymology": "어근이 있으면 한 줄, 없으면 빈 문자열"}],
  "pragmatics": [{"pattern": "...", "note": "미국 직장 화용 차이 한 줄(한국어)"}],
  "retry": {"goal": "다음 통화에서 쓸 목표 한두 줄(영어)", "target_phrases": ["...", "..."]}
}"""

_PROMPT_TEMPLATE = """You are an expert English speaking coach for a Korean learner of American workplace English.

Read the call transcript below. Each dialogue line is formatted as "**Me:** ..." (the learner's own speech) or "**Partner:** ..." (the native speaker they role-played with).

Analysis rules:
- Evaluate ONLY the "Me" utterances.
- Ignore repetitions and fillers ("uh", "um", "I I I", false starts) - they come from speech transcription, not real mistakes.
- Keep everything SHORT. Do not lecture or write long explanations.
- corrections: the {max_corrections} most useful fixes. "said" is the learner's phrase (lightly cleaned); "better" is a natural American phrasing; "why" is ONE short Korean sentence.
- good: up to {max_good} things the learner said well. "note" is one short Korean sentence on why it worked.
- vocab: up to {max_vocab} useful words/expressions from the call. "meaning_ko" in Korean; "example" a short English sentence; "etymology" one short Korean line about the root if the word has a recognizable one, otherwise "".
- pragmatics: American workplace pragmatic/register differences worth knowing (e.g., lead with the bottom line, apologize less, accept praise gracefully). "note" is one short Korean sentence.
- Include corrections that the Partner already pointed out during the call.
- retry.goal: 1-2 English sentences describing what to focus on in the next call of the same scene.
- retry.target_phrases: 2-4 short English phrases the learner should try to use next time.

Return ONLY valid JSON with exactly this shape (no markdown fences, no commentary, no extra keys):
{contract}

TRANSCRIPT:
---
{transcript}
---"""


def build_prompt(transcript: str) -> str:
    """분석 지침과 대화 전문을 합쳐 모델 프롬프트를 만든다."""
    return _PROMPT_TEMPLATE.format(
        max_corrections=MAX_CORRECTIONS,
        max_good=MAX_GOOD,
        max_vocab=MAX_VOCAB,
        contract=_CONTRACT_HINT,
        transcript=transcript,
    )


def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def extract_json(raw: Any) -> Dict[str, Any]:
    """모델 응답에서 JSON 객체를 꺼낸다.

    dict면 그대로, 문자열이면 코드펜스를 벗기고 첫 `{`부터 마지막 `}`까지 파싱한다.
    """
    if isinstance(raw, dict):
        return raw
    text = _clean_str(raw)
    if not text:
        raise ValueError("빈 응답")
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("JSON 객체를 찾을 수 없습니다")
    data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("JSON 객체가 아닙니다")
    return data


def _rows(data: Dict[str, Any], key: str, fields: List[str], limit: int) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    raw = data.get(key)
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        row = {field: _clean_str(item.get(field)) for field in fields}
        if not any(row.values()):
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def normalize_tutor_json(raw: Any) -> Dict[str, Any]:
    """모델 출력을 고정 계약 모양으로 정리한다(누락 키 기본값, 개수 제한)."""
    data = extract_json(raw)

    retry_raw = data.get("retry") if isinstance(data.get("retry"), dict) else {}
    phrases = [
        _clean_str(p)
        for p in (retry_raw.get("target_phrases") or [])
        if _clean_str(p)
    ][:MAX_PHRASES]

    return {
        "corrections": _rows(data, "corrections", ["said", "better", "why"], MAX_CORRECTIONS),
        "good": _rows(data, "good", ["said", "note"], MAX_GOOD),
        "vocab": _rows(data, "vocab", ["word", "meaning_ko", "example", "etymology"], MAX_VOCAB),
        "pragmatics": _rows(data, "pragmatics", ["pattern", "note"], MAX_PRAGMATICS),
        "retry": {
            "goal": _clean_str(retry_raw.get("goal")),
            "target_phrases": phrases,
        },
    }


def is_empty_result(data: Dict[str, Any]) -> bool:
    """계약 JSON의 5개 섹션이 모두 비었는지 본다.

    corrections·good·vocab·pragmatics와 retry의 goal·target_phrases가 전부
    비면 분석 실패로 본다(모델이 빈 JSON을 돌려준 경우).
    """
    retry = data.get("retry") if isinstance(data.get("retry"), dict) else {}
    return not (
        data.get("corrections")
        or data.get("good")
        or data.get("vocab")
        or data.get("pragmatics")
        or retry.get("goal")
        or retry.get("target_phrases")
    )


def _make_client() -> genai.Client:
    """ADC로 Vertex AI 클라이언트를 만든다(새 키 없음)."""
    project = get_project_id()
    location = os.getenv("LOCATION", "us-central1")
    return genai.Client(vertexai=True, project=project, location=location)


VERBATIM_PROMPT = (
    "Transcribe this recording of an English learner VERBATIM. Do NOT fix grammar, "
    "tense, plurals, articles, prepositions or word choice. Keep fillers (um, uh), "
    "repetitions and false starts. If a word or word ending is acoustically ambiguous "
    "(e.g. start vs started, work vs worked, this vs these), write both as "
    "[start/started?]. Write Korean words in Hangul as heard. One line per utterance. "
    "Plain text only."
)

_VERBATIM_SECTION = """

LEARNER VERBATIM (raw microphone transcription, NOT corrected - authoritative for what the learner actually said; the **Me:** lines above were auto-corrected by live ASR):
---
{verbatim}
---
Base corrections on the VERBATIM text when it differs from the Me: lines.
For each [a/b?] item, add a correction whose `why` (Korean) says the pronunciation was unclear (e.g. '-ed 끝소리가 약해 started가 start로 들렸어요')."""


def with_verbatim(prompt: str, verbatim: Optional[str]) -> str:
    """프롬프트 끝에 VERBATIM 섹션을 붙인다(받아쓰기가 없으면 그대로)."""
    if not verbatim:
        return prompt
    return prompt + _VERBATIM_SECTION.format(verbatim=verbatim)


def transcribe_verbatim(wav_path, *, model_name: Optional[str] = None) -> str:
    """마이크 원음 WAV를 교정 없이 들린 그대로 받아쓴다(Vertex, TUTOR_MODEL)."""
    data = Path(wav_path).read_bytes()
    client = _make_client()
    chosen_model = model_name or os.getenv(TUTOR_MODEL_ENV, DEFAULT_TUTOR_MODEL)
    response = client.models.generate_content(
        model=chosen_model,
        contents=[types.Part.from_bytes(data=data, mime_type="audio/wav"), VERBATIM_PROMPT],
    )
    return (response.text or "").strip()


def _verbatim_for(
    transcript_path,
    verbatim_dir: Path,
    transcribe: Optional[Callable[[Any], str]],
) -> Optional[str]:
    """같은 stem의 wav가 있으면 받아쓰고 verbatim.txt로 저장한다. wav는 항상 지운다.

    받아쓰기가 실패하면 경고만 남기고 None(전문만으로 분석한다).
    """
    stem = Path(transcript_path).stem
    wav = get_audio_dir() / (stem + ".wav")
    if not wav.is_file():
        return None
    text: Optional[str] = None
    try:
        text = (transcribe or transcribe_verbatim)(wav)
        text = (text or "").strip() or None
        if text:
            try:
                verbatim_dir.mkdir(parents=True, exist_ok=True)
                (verbatim_dir / (stem + ".verbatim.txt")).write_text(text + "\n", encoding="utf-8")
            except OSError as e:
                logger.error("받아쓰기 원문 저장 실패 %s: %s", verbatim_dir, e)
    except Exception as e:  # noqa: BLE001 - 실패해도 전문만으로 분석한다
        logger.warning("들린 그대로 받아쓰기 실패, 전문만으로 분석합니다: %s", e)
        text = None
    finally:
        try:
            wav.unlink()
        except OSError as e:
            logger.warning("원음 WAV 삭제 실패 %s: %s", wav, e)
    return text


def analyze_transcript(
    transcript: str,
    *,
    generate_text: Optional[Callable[[str], Any]] = None,
    model_name: Optional[str] = None,
    verbatim: Optional[str] = None,
) -> Dict[str, Any]:
    """대화 전문을 분석해 계약 JSON을 돌려준다.

    generate_text를 주면 그걸 호출한다(테스트용). 없으면 Vertex AI 텍스트 모델을
    한 번 부르고, 파싱에 실패하면 한 번 더 시도한다.
    """
    if generate_text is None:
        client = _make_client()
        chosen_model = model_name or os.getenv(TUTOR_MODEL_ENV, DEFAULT_TUTOR_MODEL)

        def generate_text(prompt: str) -> Any:  # noqa: F811 - 의도적 기본 구현
            response = client.models.generate_content(
                model=chosen_model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return response.text

    prompt = with_verbatim(build_prompt(transcript), verbatim)
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            result = normalize_tutor_json(generate_text(prompt))
            if is_empty_result(result):
                raise ValueError("빈 결과(5개 섹션이 모두 비었습니다)")
            return result
        except Exception as e:  # noqa: BLE001 - 파싱 실패는 재시도 대상
            last_error = e
            logger.warning("튜터링 JSON 파싱 실패(시도 %d/2): %s", attempt + 1, e)

    raise TutoringAnalysisError(f"튜터링 분석 실패: {last_error}") from last_error


def save_tutoring(data: Dict[str, Any], transcript_path) -> Optional[Path]:
    """튜터링 결과를 tutoring/<같은 파일명>.json으로 저장한다.

    저장에 실패해도 예외를 던지지 않고 로그만 남기고 None을 돌려준다
    (transcript_store.py와 같은 정책).
    """
    directory = get_tutoring_dir()
    path = directory / (Path(transcript_path).stem + ".json")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        logger.error("튜터링 결과 저장 실패 %s: %s", path, e)
        return None
    return path


def run_tutoring(
    transcript_path,
    *,
    generate_text: Optional[Callable[[str], Any]] = None,
    transcribe: Optional[Callable[[Any], str]] = None,
) -> Tuple[Dict[str, Any], bool]:
    """전문 파일을 읽어 분석·저장하고 (계약 JSON, 저장 성공 여부)를 돌려준다.

    분석이 실패(빈 결과 포함)하면 예외를 그대로 올리며, 이때 저장은 하지 않아
    기존 JSON을 빈 내용으로 덮어쓰지 않는다.
    """
    path = Path(transcript_path)
    text = path.read_text(encoding="utf-8")
    verbatim = _verbatim_for(path, get_tutoring_dir(), transcribe)
    data = analyze_transcript(text, generate_text=generate_text, verbatim=verbatim)
    saved = save_tutoring(data, path) is not None
    return data, saved


def tutor_transcript(transcript_path, *, generate_text: Optional[Callable[[str], Any]] = None) -> Dict[str, Any]:
    """전문 파일을 읽어 분석하고, 결과를 저장한 뒤 계약 JSON을 돌려준다."""
    data, _saved = run_tutoring(transcript_path, generate_text=generate_text)
    return data


# --- teach-back(가르치며 배우기) 분석 ---------------------------------------
#
# 일반 튜터링과 분석 대상이 다르다. 사용자(=선생님)가 자기 학습 노트를 영어로
# 가르친 수업에서, 학생 질문에 충분히 답하지 못한 것만 골라 원인과 함께 기록한다.
# 응답은 일반 5키 + unanswered + lesson_date이고, 저장 위치도 teachback/이다.

_TEACHBACK_CONTRACT_HINT = """{
  "unanswered": [{"question": "Maya: ...", "teacher_said": "...", "cause": "english|understanding|both|unclear", "evidence": "한국어 한 줄", "parked": true}],
  "corrections": [{"said": "...", "better": "...", "why": "한국어 한두 문장"}],
  "good": [{"said": "...", "note": "왜 좋았는지 한 줄(한국어)"}],
  "vocab": [{"word": "...", "meaning_ko": "...", "example": "...", "etymology": "어근이 있으면 한 줄, 없으면 빈 문자열"}],
  "pragmatics": [{"pattern": "...", "note": "미국 중학생에게 말할 때의 화용 차이 한 줄(한국어)"}],
  "retry": {"goal": "다음 수업에서 고칠 점 한두 줄(영어)", "target_phrases": ["...", "..."]}
}"""

_TEACHBACK_PROMPT_TEMPLATE = """You are an expert English teaching coach analyzing a "teach-back" lesson.

In this lesson the learner was the TEACHER. They explained their own study notes in English to a class of three American middle-school students (about 13): Maya (curious, asks "Why?"), Leo (asks what words mean), Sam (asks for everyday examples). A senior teacher, Ms. Park, may also speak.

Transcript line format:
- "**Me:** ..." = the teacher (the learner). These are the lines being evaluated.
- "**Partner:** ..." = everything said by the class. Inside a Partner line, the speaker is prefixed with "Maya:", "Leo:", "Sam:" (a student) or "Quick note from Ms. Park" (the senior teacher).

Analysis rules:
- For EACH student question, decide whether the teacher's answer was enough for a 13-year-old to understand. If it was enough, do NOT include it.
- cause is exactly one of:
  - "english": the teacher seems to know the content but could not put it into English (fell back into Korean, stalled a long time, asked "how do you say", or had the right fragments from the notes).
  - "understanding": the content was wrong, vague, circular, or the teacher said "I don't know".
  - "both": a mix of the two.
  - "unclear": you cannot tell.
- "question": short, keep the student's name prefix, e.g. "Maya: ...".
- "teacher_said": a short quote of the teacher's answer, or "" if they never answered.
- "evidence": ONE short sentence in KOREAN explaining why it was not enough.
- "parked": true only if the teacher deferred with something like "let me check and get back to you".
- Use the HIDDEN NOTES below as the answer key. Do NOT use content that is not in the notes as evidence of understanding.
- Reflect Ms. Park's interventions in the corrections sections.
- At most {max_unanswered} questions in "unanswered".
- Also fill the usual coaching sections. Explanations ("why", "note", "meaning_ko", "etymology") are in Korean; retry.goal and target_phrases are English. retry.goal is what to fix in the next lesson.

Return ONLY valid JSON with exactly this shape (no markdown fences, no commentary, no extra keys):
{contract}

HIDDEN NOTES (the teacher's own study notes; for you only):
---
{lesson_text}
---

TRANSCRIPT:
---
{transcript}
---"""


def build_teachback_prompt(transcript: str, lesson_text: str) -> str:
    """teach-back 분석 지침·숨은 노트·대화 전문을 합쳐 모델 프롬프트를 만든다."""
    return _TEACHBACK_PROMPT_TEMPLATE.format(
        max_unanswered=MAX_UNANSWERED,
        contract=_TEACHBACK_CONTRACT_HINT,
        lesson_text=lesson_text,
        transcript=transcript,
    )


def _unanswered_rows(data: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    """unanswered 행을 계약 모양으로 정리한다(cause는 4개 중 하나로 고정)."""
    rows: List[Dict[str, Any]] = []
    raw = data.get("unanswered")
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if not isinstance(item, dict):
            continue
        cause = _clean_str(item.get("cause")).lower()
        if cause not in CAUSES:
            cause = "unclear"
        row = {
            "question": _clean_str(item.get("question")),
            "teacher_said": _clean_str(item.get("teacher_said")),
            "cause": cause,
            "evidence": _clean_str(item.get("evidence")),
            "parked": bool(item.get("parked")),
        }
        if not (row["question"] or row["teacher_said"] or row["evidence"]):
            continue
        rows.append(row)
        if len(rows) >= limit:
            break
    return rows


def normalize_teachback_json(raw: Any, *, max_unanswered: int = MAX_UNANSWERED) -> Dict[str, Any]:
    """teach-back 모델 출력을 고정 계약 모양으로 정리한다.

    일반 5키(corrections·good·vocab·pragmatics·retry)에 unanswered를 더한다.
    """
    data = extract_json(raw)
    result = normalize_tutor_json(data)
    result["unanswered"] = _unanswered_rows(data, max_unanswered)
    return result


def is_empty_teachback_result(data: Dict[str, Any]) -> bool:
    """일반 5키가 모두 비고 unanswered도 비었으면 분석 실패로 본다."""
    return not data.get("unanswered") and is_empty_result(data)


def analyze_teachback(
    transcript: str,
    lesson_text: str,
    *,
    generate_text: Optional[Callable[[str], Any]] = None,
    model_name: Optional[str] = None,
    verbatim: Optional[str] = None,
) -> Dict[str, Any]:
    """수업 전문과 숨은 노트를 분석해 teach-back 계약 JSON을 돌려준다.

    generate_text를 주면 그걸 호출한다(테스트용). 없으면 Vertex AI 텍스트
    모델을 부르고, 파싱 실패나 빈 결과면 한 번 재시도한다.
    """
    if generate_text is None:
        client = _make_client()
        chosen_model = model_name or os.getenv(TUTOR_MODEL_ENV, DEFAULT_TUTOR_MODEL)

        def generate_text(prompt: str) -> Any:  # noqa: F811 - 의도적 기본 구현
            response = client.models.generate_content(
                model=chosen_model,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            return response.text

    prompt = with_verbatim(build_teachback_prompt(transcript, lesson_text), verbatim)
    last_error: Optional[Exception] = None
    for attempt in range(2):
        try:
            result = normalize_teachback_json(generate_text(prompt))
            if is_empty_teachback_result(result):
                raise ValueError("빈 결과(teach-back: 5개 섹션과 unanswered가 모두 비었습니다)")
            return result
        except Exception as e:  # noqa: BLE001 - 파싱 실패는 재시도 대상
            last_error = e
            logger.warning("teach-back JSON 파싱 실패(시도 %d/2): %s", attempt + 1, e)

    raise TutoringAnalysisError(f"teach-back 분석 실패: {last_error}") from last_error


def save_teachback(data: Dict[str, Any], transcript_path) -> Optional[Path]:
    """teach-back 결과를 teachback/<같은 파일명>.json으로 저장한다.

    저장에 실패해도 예외를 던지지 않고 로그만 남기고 None을 돌려준다.
    """
    directory = get_teachback_dir()
    path = directory / (Path(transcript_path).stem + ".json")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as e:
        logger.error("teach-back 결과 저장 실패 %s: %s", path, e)
        return None
    return path


def run_teachback(
    transcript_path,
    lesson_text: str,
    lesson_date: str,
    *,
    generate_text: Optional[Callable[[str], Any]] = None,
    transcribe: Optional[Callable[[Any], str]] = None,
) -> Tuple[Dict[str, Any], bool]:
    """수업 전문을 읽어 분석·저장하고 (계약 JSON, 저장 성공 여부)를 돌려준다.

    응답 dict에는 lesson_date가 들어간다. 분석이 실패하면 예외를 올리며 저장하지
    않아 기존 JSON을 빈 내용으로 덮어쓰지 않는다.
    """
    path = Path(transcript_path)
    text = path.read_text(encoding="utf-8")
    verbatim = _verbatim_for(path, get_teachback_dir(), transcribe)
    data = analyze_teachback(text, lesson_text, generate_text=generate_text, verbatim=verbatim)
    data["lesson_date"] = lesson_date
    saved = save_teachback(data, path) is not None
    return data, saved


def latest_transcript_path(directory=None) -> Optional[Path]:
    """sessions/ 안에서 형식에 맞는 가장 최근 .md 파일을 돌려준다."""
    directory = Path(directory) if directory else get_transcript_dir()
    try:
        files = [p for p in directory.glob("*.md") if FILENAME_RE.fullmatch(p.name)]
    except OSError:
        return None
    if not files:
        return None
    return max(files, key=lambda p: (p.stat().st_mtime, p.name))


def latest_transcript_since(started_at_ms=None, *, directory=None) -> Optional[Path]:
    """started_at(epoch ms) 이후에 만들어진 가장 최근 전사 파일을 돌려준다.

    started_at_ms가 없으면 가장 최근 파일을 쓴다. mtime이 started_at/1000 - 2초
    이상인 것만 후보로 삼아, 지난 통화(어제 등) 파일로 되돌아가지 않는다.
    후보가 없으면 None.
    """
    directory = Path(directory) if directory else get_transcript_dir()
    start_sec: Optional[float] = None
    if started_at_ms is not None:
        try:
            start_sec = float(started_at_ms) / 1000.0
        except (TypeError, ValueError):
            start_sec = None

    try:
        files = [p for p in directory.glob("*.md") if FILENAME_RE.fullmatch(p.name)]
    except OSError:
        return None

    candidates: List[Path] = []
    for p in files:
        if start_sec is None:
            candidates.append(p)
            continue
        try:
            if p.stat().st_mtime >= start_sec - 2.0:
                candidates.append(p)
        except OSError:
            continue

    if not candidates:
        return None
    return max(candidates, key=lambda p: (p.stat().st_mtime, p.name))


def resolve_transcript(filename=None, *, directory=None) -> Path:
    """클라이언트가 준 파일명을 sessions/ 안으로 안전하게 해석한다.

    파일명이 없으면 최신 파일을 쓴다. 경로 구분자나 허용 패턴 밖 이름은 거부한다.
    """
    directory = Path(directory) if directory else get_transcript_dir()
    if filename:
        name = Path(str(filename)).name
        if name != str(filename) or not FILENAME_RE.fullmatch(name):
            raise ValueError("허용되지 않은 파일명입니다")
        path = directory / name
        if not path.is_file():
            raise FileNotFoundError("해당 통화 기록이 없습니다")
        return path
    path = latest_transcript_path(directory)
    if path is None:
        raise FileNotFoundError("저장된 통화 기록이 없습니다")
    return path


if __name__ == "__main__":
    # 네트워크 없이 계약 정리 로직만 점검한다.
    _fake = json.dumps(
        {
            "corrections": [
                {"said": "I am agree", "better": "I agree", "why": "'agree'는 동사라 be동사를 쓰지 않아요."},
                "not-a-dict",
                {"said": "", "better": "", "why": ""},
            ],
            "good": [{"said": "I'll circle back.", "note": "자연스러운 구동사였어요."}],
            "vocab": [
                {"word": "circle back", "meaning_ko": "나중에 다시 논의하다", "example": "Let's circle back tomorrow.", "etymology": ""}
            ],
            "pragmatics": [{"pattern": "Bottom line first", "note": "미국 직장에선 결론을 먼저 말해요."}],
            "retry": {"goal": "Lead with your bottom line.", "target_phrases": ["Here's the bottom line", ""]},
            "extra": "ignored",
        }
    )
    _out = analyze_transcript("Me: I am agree", generate_text=lambda _prompt: _fake)
    assert set(_out) == {"corrections", "good", "vocab", "pragmatics", "retry"}, _out
    assert len(_out["corrections"]) == 1 and _out["corrections"][0]["better"] == "I agree"
    assert _out["retry"]["target_phrases"] == ["Here's the bottom line"], _out["retry"]

    # 코드펜스가 섞여도 파싱된다.
    _out = analyze_transcript("Me: hi", generate_text=lambda _p: "```json\n" + _fake + "\n```")
    assert _out["vocab"][0]["word"] == "circle back"

    # 첫 시도가 깨진 JSON이면 재시도해서 성공한다.
    _calls = {"n": 0}

    def _flaky(_prompt):
        _calls["n"] += 1
        return "not json" if _calls["n"] == 1 else _fake

    _out = analyze_transcript("Me: hi", generate_text=_flaky)
    assert _calls["n"] == 2 and _out["good"], _out

    # 경로 주입은 거부된다.
    for _bad in ("../x.md", "/etc/passwd", "a/b.md", "notes.txt"):
        try:
            resolve_transcript(_bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"거부되어야 함: {_bad}")

    # 빈 결과는 재시도(2회) 뒤 예외가 되고, 저장으로 넘어가지 않는다.
    _empty_json = (
        '{"corrections": [], "good": [], "vocab": [], "pragmatics": [], '
        '"retry": {"goal": "", "target_phrases": []}}'
    )
    _empty_calls = {"n": 0}

    def _always_empty(_prompt):
        _empty_calls["n"] += 1
        return _empty_json

    try:
        analyze_transcript("Me: hi", generate_text=_always_empty)
    except TutoringAnalysisError:
        pass
    else:
        raise AssertionError("빈 결과는 예외여야 함")
    assert _empty_calls["n"] == 2, _empty_calls

    # 첫 시도만 비고 두 번째에 내용이 있으면 성공한다.
    _seq = {"n": 0}

    def _empty_then_ok(_prompt):
        _seq["n"] += 1
        return _empty_json if _seq["n"] == 1 else _fake

    _out = analyze_transcript("Me: hi", generate_text=_empty_then_ok)
    assert _seq["n"] == 2 and _out["good"], _out

    # 파일명 정규식: 줄바꿈과 비ASCII 숫자를 거부한다.
    assert FILENAME_RE.fullmatch("2026-10-12-093238.md")
    for _bad_name in (
        "2026-10-12-093238.md\n",
        "../x.md",
        "2026-1O-12-093238.md",
        "２０２６-10-12-093238.md",
    ):
        assert FILENAME_RE.fullmatch(_bad_name) is None, _bad_name

    # VERBATIM: wav가 있으면 섹션이 프롬프트에 들어가고 wav가 지워진다. 없으면 기존과 같다.
    import tempfile

    with tempfile.TemporaryDirectory() as _tmp:
        _tp = Path(_tmp)
        os.environ["AUDIO_DIR"] = str(_tp / "audio")
        os.environ["TUTORING_DIR"] = str(_tp / "tutoring")
        os.environ["TEACHBACK_DIR"] = str(_tp / "teachback")
        (_tp / "audio").mkdir()
        _md = _tp / "2026-10-16-100000.md"
        _md.write_text("**Me:** I just started my day\n", encoding="utf-8")
        _seen = []

        def _gen(prompt):
            _seen.append(prompt)
            return _fake

        # 1) wav 없음: 섹션 없음, 받아쓰기 호출 없음
        def _no_call(_p):
            raise AssertionError("wav가 없으면 호출되면 안 됨")

        run_tutoring(_md, generate_text=_gen, transcribe=_no_call)
        assert "LEARNER VERBATIM" not in _seen[-1]

        # 2) wav 있음: 섹션 포함, wav 삭제, verbatim.txt 저장
        _wav = _tp / "audio" / "2026-10-16-100000.wav"
        _wav.write_bytes(b"RIFF")
        run_tutoring(_md, generate_text=_gen, transcribe=lambda _p: "I just [start/started?] my day")
        assert "LEARNER VERBATIM" in _seen[-1] and "[start/started?]" in _seen[-1]
        assert "Base corrections on the VERBATIM" in _seen[-1]
        assert not _wav.exists()
        assert (_tp / "tutoring" / "2026-10-16-100000.verbatim.txt").exists()

        # 3) 받아쓰기 실패: 전문만으로 분석하고 wav는 지운다
        _wav.write_bytes(b"RIFF")

        def _boom(_p):
            raise RuntimeError("down")

        run_tutoring(_md, generate_text=_gen, transcribe=_boom)
        assert "LEARNER VERBATIM" not in _seen[-1] and not _wav.exists()

    print("tutor self-check OK")

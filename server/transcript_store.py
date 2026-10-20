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

"""통화가 끝난 뒤 대화 전문을 마크다운 파일로 저장한다.

표준 라이브러리만 사용한다. 서버가 죽지 않도록 쓰기 실패는 로그만 남기고
None을 돌려주지만, 조용히 넘어가지 않고 원인과 경로를 logger.error에 남긴다.
"""

import logging
import os
import re
import tempfile
import time
import wave
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

Chunk = Tuple[str, str]
Turn = Tuple[str, str]

LEARNER_SPEAKER = "Me"  # call_bot.py: 학습자(입력 전사) 쪽 라벨
_COACH_RE = re.compile(r"\b(?:coach|hint)\b", re.IGNORECASE)

_WHITESPACE = (" ", "\t", "\n", "\r")

# 통화 전문/튜터링 결과가 저장되는 위치. tutor.py도 이 helper를 재사용한다.
DEFAULT_TRANSCRIPT_DIR = "~/dev/learning/english/sessions"
TRANSCRIPT_DIR_ENV = "TRANSCRIPT_DIR"
TUTORING_DIR_ENV = "TUTORING_DIR"
TEACHBACK_DIR_ENV = "TEACHBACK_DIR"

# 마이크 원음(WAV) 임시 보관 위치. 받아쓰기가 끝나면 tutor.py가 지운다.
DEFAULT_AUDIO_DIR = "~/.cache/immergo/audio"
AUDIO_DIR_ENV = "AUDIO_DIR"
AUDIO_MAX_AGE_SEC = 24 * 60 * 60


def get_transcript_dir() -> Path:
    """통화 전문(sessions) 폴더. TRANSCRIPT_DIR가 있으면 그걸 쓴다."""
    override = os.getenv(TRANSCRIPT_DIR_ENV)
    return Path(os.path.expanduser(override or DEFAULT_TRANSCRIPT_DIR))


def get_tutoring_dir() -> Path:
    """튜터링 결과 폴더.

    TUTORING_DIR가 있으면 그걸 쓰고, 없으면 sessions 폴더의 형제인 tutoring/을 쓴다.
    """
    override = os.getenv(TUTORING_DIR_ENV)
    if override:
        return Path(os.path.expanduser(override))
    return get_transcript_dir().parent / "tutoring"


def get_teachback_dir() -> Path:
    """teach-back 분석 결과 폴더.

    TEACHBACK_DIR가 있으면 그걸 쓰고, 없으면 sessions 폴더의 형제인 teachback/을
    쓴다(일반 튜터링 tutoring/과 분리).
    """
    override = os.getenv(TEACHBACK_DIR_ENV)
    if override:
        return Path(os.path.expanduser(override))
    return get_transcript_dir().parent / "teachback"


def get_audio_dir() -> Path:
    """마이크 원음 WAV 폴더. AUDIO_DIR가 있으면 그걸 쓴다."""
    override = os.getenv(AUDIO_DIR_ENV)
    return Path(os.path.expanduser(override or DEFAULT_AUDIO_DIR))


def transcript_stem(started_at: str) -> str:
    """save_transcript가 정하는 파일명 stem(시작 시각 기준)을 미리 계산한다."""
    return _parse_started_at(started_at).strftime("%Y-%m-%d-%H%M%S")


def save_call_audio(pcm: bytes, stem: str, out_dir=None, *, sample_rate: int = 16000) -> Optional[Path]:
    """16bit mono PCM을 <stem>.wav로 쓰고, 24시간 넘은 wav를 지운다.

    실패해도 예외를 던지지 않고 로그만 남긴다(통화 저장을 막지 않는다).
    """
    if not pcm:
        return None
    directory = Path(out_dir).expanduser() if out_dir else get_audio_dir()
    path = directory / (stem + ".wav")
    try:
        directory.mkdir(parents=True, exist_ok=True)
        cutoff = time.time() - AUDIO_MAX_AGE_SEC
        for old in directory.glob("*.wav"):
            try:
                if old.stat().st_mtime < cutoff:
                    old.unlink()
            except OSError as e:
                logger.warning("오래된 원음 삭제 실패 %s: %s", old, e)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(bytes(pcm))
    except (OSError, wave.Error) as e:
        logger.error("원음 WAV 저장 실패 %s: %s", path, e)
        return None
    return path


def _join_pieces(left: str, right: str) -> str:
    """조각 두 개를 자연스럽게 이어 붙인다.

    이미 공백이 경계에 있으면 그대로 두고, 오른쪽 조각이 글자/숫자로 시작하면
    한 칸을 넣는다. 구두점으로 시작하는 조각("'t", ",")은 붙여 쓴다.
    """
    if not left:
        return right
    if not right:
        return left
    if left.endswith(_WHITESPACE) or right.startswith(_WHITESPACE):
        return left + right
    if right[0].isalnum():
        return left + " " + right
    return left + right


def _merge_chunks(chunks: Iterable[Chunk]) -> List[Turn]:
    """(speaker, text) 조각 목록을 화자별 연속 턴으로 합친다.

    같은 화자의 연속 조각은 하나로 잇고, 빈 텍스트는 버린다.
    """
    turns: List[Turn] = []
    current_speaker: Optional[str] = None
    current_text = ""

    for chunk in chunks:
        try:
            speaker, text = chunk
        except (TypeError, ValueError):
            continue
        if not text or not text.strip():
            continue

        if speaker == current_speaker and current_text:
            current_text = _join_pieces(current_text, text)
        else:
            if current_text:
                turns.append((current_speaker, current_text.strip()))
            current_speaker = speaker
            current_text = text

    if current_text:
        turns.append((current_speaker, current_text.strip()))

    return turns


def format_transcript(chunks: Iterable[Chunk], meta: dict) -> str:
    """대화 조각과 메타데이터를 마크다운 전문으로 만든다."""
    meta = meta or {}

    started_at = str(meta.get("started_at") or "")
    started_display = started_at[:16] if len(started_at) >= 16 else started_at
    mission = meta.get("mission") or "unknown"
    model = meta.get("model") or "unknown"

    try:
        duration_sec = int(meta.get("duration_sec") or 0)
    except (TypeError, ValueError):
        duration_sec = 0
    minutes, seconds = divmod(max(duration_sec, 0), 60)

    turns = _merge_chunks(chunks)
    completed = "yes" if meta.get("completed") else "no"
    coach_count = sum(
        len(_COACH_RE.findall(text))
        for speaker, text in turns
        if speaker == LEARNER_SPEAKER
    )

    lines = [
        f"# Call {started_display}",
        f"- mission: {mission}",
        f"- model: {model}",
        f"- duration: {minutes}m {seconds}s",
        f"- completed: {completed}",
        f"- coach: {coach_count}",
    ]
    try:
        lines.append(f"- cost_usd: {float(meta['cost_usd']):.4f}")
    except (KeyError, TypeError, ValueError):
        pass
    lines.append("")

    for speaker, text in turns:
        lines.append(f"**{speaker}:** {text}")

    return "\n".join(lines) + "\n"


def _parse_started_at(started_at: str) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(started_at, fmt)
        except (TypeError, ValueError):
            continue
    return datetime.now()


def save_transcript(chunks: Iterable[Chunk], meta: dict, out_dir) -> Optional[Path]:
    """턴이 하나라도 있으면 마크다운 파일로 저장하고 경로를 돌려준다.

    턴이 없으면 저장하지 않고 None. 저장에 실패해도 예외를 밖으로 던지지
    않지만 logger.error에 원인과 경로를 남긴다.
    """
    chunks = list(chunks)
    turns = _merge_chunks(chunks)
    if not turns:
        return None

    meta = meta or {}
    content = format_transcript(chunks, meta)

    directory = Path(out_dir).expanduser()
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        logger.error("대화 전문 폴더를 만들 수 없습니다 %s: %s", directory, e)
        return None

    start = _parse_started_at(str(meta.get("started_at") or ""))
    path = directory / (start.strftime("%Y-%m-%d-%H%M%S") + ".md")

    try:
        path.write_text(content, encoding="utf-8")
    except OSError as e:
        logger.error("대화 전문 저장 실패 %s: %s", path, e)
        return None

    return path


if __name__ == "__main__":
    _meta = {
        "started_at": "2026-10-07 14:03:07",
        "duration_sec": 65,
        "model": "gemini-live-2.5-flash-native-audio",
        "mission": None,
    }

    # 1) 같은 화자의 연속 조각은 한 턴으로 합쳐진다 (공백 처리 포함).
    _out = format_transcript([("Me", "Hello"), ("Me", "world")], _meta)
    assert "**Me:** Hello world" in _out, _out

    # 2) 빈 텍스트는 버린다.
    _out = format_transcript([("Me", "Hi"), ("Me", "   "), ("Me", "")], _meta)
    assert _out.count("**Me:**") == 1, _out
    assert "**Me:** Hi" in _out, _out

    # 3) 화자가 바뀌면 새 턴이 된다 (순서 유지).
    _out = format_transcript(
        [("Me", "Hi"), ("Partner", "Hello"), ("Me", "Bye")], _meta
    )
    assert "**Me:** Hi\n**Partner:** Hello\n**Me:** Bye" in _out, _out

    # 4) 헤더 형식과 duration 표기.
    assert _out.startswith("# Call 2026-10-07 14:03\n"), _out
    assert "- mission: unknown" in _out, _out
    assert "- duration: 1m 5s" in _out, _out

    # 5) 턴이 없으면 저장하지 않고 None.
    with tempfile.TemporaryDirectory() as _tmp:
        assert save_transcript([], _meta, _tmp) is None
        assert save_transcript([("Me", " ") ], _meta, _tmp) is None

        # 6) 턴이 있으면 파일명이 시작 시각 기준으로 만들어진다.
        _path = save_transcript([("Me", "Hi")], _meta, _tmp)
        assert _path is not None and _path.exists(), _path
        assert _path.name == "2026-10-07-140307.md", _path.name

    print("transcript_store self-check OK")

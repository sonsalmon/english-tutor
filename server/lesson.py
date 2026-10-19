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

"""`GET /api/lesson` 로직과 세션 제한 시간 계산.

그날의 학습 기록(마크다운)을 작업실(workroom)의 거르기 코드로 걸러 절 목록을
만든다. 거름망을 다시 구현하지 않고 `scripts/lesson_dump.py`를 하위 프로세스로
실행해 JSON을 받는다(두 저장소의 가상환경이 달라 import보다 안전).

- 학습 폴더: `LEARNING_ROOT`(기본 ~/dev/learning) 아래 `<topic>/learning-records/`.
- 차단어 파일: `WORKROOM_DATA_DIR`(기본 ~/.workroom) 아래 blocklist.txt.
- 작업실 코드 경로: `WORKROOM_CLI_DIR`(기본 ~/dev/workroom/cli)를 PYTHONPATH로.
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# 날짜는 ASCII 숫자만, fullmatch(경로 주입·비ASCII 숫자·줄바꿈 방지).
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)

DEFAULT_TOPIC = "security-career"
DEFAULT_LEARNING_ROOT = "~/dev/learning"
DEFAULT_WORKROOM_DATA_DIR = "~/.workroom"
DEFAULT_WORKROOM_CLI_DIR = "~/dev/workroom/cli"

LEARNING_ROOT_ENV = "LEARNING_ROOT"
WORKROOM_DATA_DIR_ENV = "WORKROOM_DATA_DIR"
WORKROOM_CLI_DIR_ENV = "WORKROOM_CLI_DIR"
TOPIC_ENV = "LEARNING_TOPIC"
PYTHON_ENV = "LESSON_PYTHON"

# 모델에 넘길 수업 글 최대 길이(절 본문 합계).
MAX_LESSON_TEXT = 6000

# scripts/lesson_dump.py 하위 프로세스 시간 제한(초). 넘으면 504.
LESSON_SUBPROCESS_TIMEOUT_SEC = 15

# 계약 2: 세션 제한 시간.
TEACHBACK_MODE = "teachback"
SESSION_TIME_LIMIT_ENV = "SESSION_TIME_LIMIT"
TEACHBACK_TIME_LIMIT_ENV = "TEACHBACK_TIME_LIMIT"
DEFAULT_SESSION_TIME_LIMIT = 180
DEFAULT_TEACHBACK_TIME_LIMIT = 900


class LessonError(RuntimeError):
    """수업 자료를 만들지 못한 경우. status_code로 HTTP 상태를 정한다."""

    status_code = 500


class LessonNotFoundError(LessonError):
    status_code = 404


class LessonBlocklistError(LessonError):
    """차단어 목록이 없거나 깨졌다. 거르지 않은 원문으로 대체하지 않는다."""

    status_code = 500


class LessonDateError(LessonError):
    status_code = 400


class LessonTimeoutError(LessonError):
    """lesson_dump.py 하위 프로세스가 시간 제한을 넘겼다."""

    status_code = 504


def resolve_session_time_limit(
    mode: Optional[str],
    session_time_limit: int,
    teachback_time_limit: Optional[int] = None,
) -> int:
    """mode에 따른 세션 제한 시간(초).

    `mode == "teachback"`이면 teachback 제한(없으면 기본 900), 아니면 기존 값.
    """
    if mode == TEACHBACK_MODE:
        if teachback_time_limit is None:
            return DEFAULT_TEACHBACK_TIME_LIMIT
        return teachback_time_limit
    return session_time_limit


def session_time_limit_from_env(mode: Optional[str], env=None) -> int:
    """환경변수에서 세션 제한 시간을 읽어 mode에 맞게 돌려준다.

    `SESSION_TIME_LIMIT`(기본 180), `TEACHBACK_TIME_LIMIT`(기본 900).
    """
    env = os.environ if env is None else env
    session = int(env.get(SESSION_TIME_LIMIT_ENV, str(DEFAULT_SESSION_TIME_LIMIT)))
    teachback = int(env.get(TEACHBACK_TIME_LIMIT_ENV, str(DEFAULT_TEACHBACK_TIME_LIMIT)))
    return resolve_session_time_limit(mode, session, teachback)


def validate_date(date: Optional[str]) -> Optional[str]:
    """date를 검사한다. 없으면 None, 형식이 틀리면 LessonDateError."""
    if date is None:
        return None
    if not isinstance(date, str) or DATE_RE.fullmatch(date) is None:
        raise LessonDateError("날짜 형식이 올바르지 않습니다(YYYY-MM-DD).")
    return date


def lesson_text(lesson: Dict[str, Any]) -> str:
    """모델에 넘길 수업 글. 프런트 `_lessonText`와 같은 형식으로 이어 자른다.

    각 절을 `## heading\nbody`로 만들고(제목이 빈 절은 본문만), 빈 절은 빼고
    `\n\n`로 이어 붙인 뒤 MAX_LESSON_TEXT자에서 자른다.
    """
    if not isinstance(lesson, dict):
        return ""
    sections = lesson.get("sections")
    if not isinstance(sections, list):
        return ""

    parts = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        heading = section.get("heading")
        body = section.get("body")
        heading = heading.strip() if isinstance(heading, str) else ""
        body = body.strip() if isinstance(body, str) else ""
        chunk = f"## {heading}\n{body}" if heading else body
        chunk = chunk.strip()
        if chunk:
            parts.append(chunk)
    return "\n\n".join(parts)[:MAX_LESSON_TEXT]


def _lesson_script_path() -> Path:
    return Path(__file__).resolve().parent.parent / "scripts" / "lesson_dump.py"


def _subprocess_env() -> Dict[str, str]:
    env = dict(os.environ)
    cli_dir = os.path.expanduser(env.get(WORKROOM_CLI_DIR_ENV) or DEFAULT_WORKROOM_CLI_DIR)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = cli_dir + (os.pathsep + existing if existing else "")
    if not env.get(LEARNING_ROOT_ENV):
        env[LEARNING_ROOT_ENV] = DEFAULT_LEARNING_ROOT
    if not env.get(WORKROOM_DATA_DIR_ENV):
        env[WORKROOM_DATA_DIR_ENV] = DEFAULT_WORKROOM_DATA_DIR
    if not env.get(TOPIC_ENV):
        env[TOPIC_ENV] = DEFAULT_TOPIC
    return env


def _raise_for_error(data: Dict[str, Any]) -> None:
    message = data.get("message") or "수업 자료를 만들지 못했습니다."
    kind = data.get("error")
    if kind == "no_records":
        raise LessonNotFoundError(message)
    if kind == "blocklist":
        raise LessonBlocklistError(message)
    if kind == "bad_date":
        raise LessonDateError(message)
    raise LessonError(message)


def get_lesson(date: Optional[str] = None) -> Dict[str, Any]:
    """그날의 수업 자료(계약 1 JSON)를 작업실 코드로 걸러 돌려준다.

    date가 없으면 가장 최근 기록을 쓴다. 차단어 목록이 없거나 깨졌으면
    LessonBlocklistError(500), 기록이 없으면 LessonNotFoundError(404),
    date 형식이 틀리면 LessonDateError(400).
    """
    validated = validate_date(date)

    script = _lesson_script_path()
    python = os.environ.get(PYTHON_ENV) or "python3"
    cmd = [python, str(script)]
    if validated:
        cmd += ["--date", validated]

    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=_subprocess_env(),
            timeout=LESSON_SUBPROCESS_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired as e:
        logger.error("lesson_dump 시간 초과(%ss)", LESSON_SUBPROCESS_TIMEOUT_SEC)
        raise LessonTimeoutError("수업 기록을 읽는 데 너무 오래 걸려요.") from e
    except OSError as e:
        logger.error("lesson_dump 실행 실패: %s", e)
        raise LessonError("수업 자료를 읽지 못했습니다.") from e

    stdout = (completed.stdout or "").strip()
    try:
        data = json.loads(stdout) if stdout else {}
    except json.JSONDecodeError as e:
        logger.error("lesson_dump 출력 파싱 실패(rc=%s): %s", completed.returncode, e)
        raise LessonError("수업 자료를 읽지 못했습니다.") from e

    if completed.returncode != 0 or not isinstance(data, dict) or data.get("error"):
        if isinstance(data, dict) and data.get("error"):
            _raise_for_error(data)
        logger.error("lesson_dump 실패(rc=%s): %s", completed.returncode, (completed.stderr or "").strip())
        raise LessonError("수업 자료를 읽지 못했습니다.")

    return data

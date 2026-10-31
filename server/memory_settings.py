"""기억 설정 파일 (memory-settings.json): "나에 대한 기억" 화면이 저장하는 값.

MEMORY_SETTINGS_PATH 의 JSON 한 개에 두 가지를 둔다.
- about_me: 친구들과 Ms. Park이 알았으면 하는 나에 대한 글(학습자가 직접 쓴다. 1500자 이하).
- remember: 자동 기억 종류별 스위치. facts(내가 말한 사실·성찰·대화 요약), threads(지난 화제 이어 가기),
  interests(학습자 카드의 관심사).

스위치는 프롬프트를 만들 때(화면)와 기억을 저장할 때(서버)에 모두 쓰인다. 서버는 갱신할 때마다
load_settings()로 다시 읽는다(호출 사이에 캐시하지 않는다). 파일이 없거나 깨졌으면 기본값이다.
표준 라이브러리만 쓰며 server.* 를 가져오지 않는다(단위 시험이 server/ 안에서 바로 돈다).
"""

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SETTINGS_PATH_ENV = "MEMORY_SETTINGS_PATH"
DEFAULT_SETTINGS_PATH = "~/dev/learning/english/memory-settings.json"
SETTINGS_VERSION = 1
ABOUT_ME_MAX = 1500
REMEMBER_KEYS = ("facts", "threads", "interests")

KST = timezone(timedelta(hours=9))
_LOCK = threading.Lock()


def get_settings_path() -> Path:
    return Path(os.path.expanduser(os.getenv(SETTINGS_PATH_ENV) or DEFAULT_SETTINGS_PATH))


def default_settings() -> Dict[str, Any]:
    return {
        "version": SETTINGS_VERSION,
        "about_me": "",
        "remember": {key: True for key in REMEMBER_KEYS},
        "updated": "",
    }


def validate_settings(payload: Any) -> Dict[str, Any]:
    """PUT 본문을 검사해 정리된 설정(updated 제외)을 돌려준다. 틀리면 ValueError. 모르는 키는 무시한다."""
    if not isinstance(payload, dict):
        raise ValueError("설정이 JSON 객체가 아닙니다")
    about_me = payload.get("about_me")
    if not isinstance(about_me, str):
        raise ValueError("about_me는 문자열이어야 합니다")
    about_me = about_me.strip()
    if len(about_me) > ABOUT_ME_MAX:
        raise ValueError(f"about_me는 {ABOUT_ME_MAX}자 이하여야 합니다")
    remember = payload.get("remember")
    if not isinstance(remember, dict):
        raise ValueError("remember는 객체여야 합니다")
    switches: Dict[str, bool] = {}
    for key in REMEMBER_KEYS:
        value = remember.get(key)
        if not isinstance(value, bool):
            raise ValueError(f"remember.{key}는 true 또는 false여야 합니다")
        switches[key] = value
    return {"version": SETTINGS_VERSION, "about_me": about_me, "remember": switches}


def load_settings() -> Dict[str, Any]:
    """저장된 설정을 읽는다. 파일이 없거나 깨졌으면 기본값(예외를 던지지 않는다)."""
    path = get_settings_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default_settings()
    except (OSError, UnicodeDecodeError) as e:
        logger.error("기억 설정을 읽을 수 없어 기본값을 씁니다 %s: %s", path, e)
        return default_settings()
    try:
        parsed = json.loads(raw)
        data = validate_settings(parsed)
    except ValueError as e:  # JSONDecodeError도 ValueError
        logger.error("기억 설정 형식이 틀려 기본값을 씁니다 %s: %s", path, e)
        return default_settings()
    updated = parsed.get("updated")
    return {**data, "updated": updated if isinstance(updated, str) else ""}


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


def save_settings(payload: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """설정을 검사해 저장하고 저장한 값을 돌려준다. 검사에 실패하면 ValueError(파일은 그대로)."""
    data = validate_settings(payload)
    now = now or datetime.now(KST)
    saved = {**data, "updated": now.astimezone(KST).isoformat(timespec="seconds")}
    with _LOCK:
        _write_atomic(get_settings_path(), saved)
    return saved

"""저장된 통화 기록을 목록·누적 합계·상세로 읽는다.

통화 전문(sessions/*.md)의 머리글만 읽고, 튜터링 결과는 tutoring/·teachback/의
같은 stem JSON을 찾는다. 읽기 전용이며 표준 라이브러리와 transcript_store만 쓴다.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from itertools import islice
from pathlib import Path
from typing import Any, Dict, List, Optional

from server.call_bot import NOISE_MARK_RE
from server.pricing import combine_cost
from server.transcript_store import get_teachback_dir, get_transcript_dir, get_tutoring_dir

logger = logging.getLogger(__name__)

STEM_RE = re.compile(r"\d{4}-\d{2}-\d{2}-\d{6}", re.ASCII)
_HEADER_RE = re.compile(r"# Call (\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*", re.ASCII)
_DURATION_RE = re.compile(r"- duration: (\d+)m (\d+)s\s*", re.ASCII)
_MISSION_RE = re.compile(r"- mission: (.*)")
_COMPLETED_RE = re.compile(r"- completed: (yes|no)\s*", re.ASCII)
_COST_RE = re.compile(r"- cost_usd: (\d+(?:\.\d+)?)\s*", re.ASCII)
_VOICE_RE = re.compile(r"- voice: (\S+)\s*")
_TURN_RE = re.compile(r"\*\*(Me|Partner):\*\*(?: (.*))?")
_HEADER_LINES = 10
# 클라이언트가 가벼운 대화 통화의 지시문에 넣는 미션 이름. 전문 머리글의 mission이 이 값이면 kind는 smalltalk.
SMALLTALK_MISSION = "Small Talk"


def _valid_stem(stem: Any) -> bool:
    return isinstance(stem, str) and STEM_RE.fullmatch(stem) is not None


def _parse_call(path: Path) -> Optional[Dict[str, Any]]:
    """전문 머리글을 읽어 통화 요약을 만든다. 머리글이 깨졌으면 None."""
    try:
        with path.open(encoding="utf-8") as f:
            head = [line.rstrip("\n") for line in islice(f, _HEADER_LINES)]
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("통화 기록을 읽지 못했어요 %s: %s", path, e)
        return None

    started = _HEADER_RE.fullmatch(head[0]) if head else None
    if not started:
        return None
    try:
        datetime.strptime(started.group(1), "%Y-%m-%d %H:%M")
    except ValueError:
        return None

    duration = mission = completed = live_cost = voice = None
    for line in head[1:]:
        if duration is None and (m := _DURATION_RE.fullmatch(line)):
            duration = int(m.group(1)) * 60 + int(m.group(2))
        elif mission is None and (m := _MISSION_RE.fullmatch(line)):
            mission = m.group(1).strip()
        elif completed is None and (m := _COMPLETED_RE.fullmatch(line)):
            completed = m.group(1) == "yes"
        elif live_cost is None and (m := _COST_RE.fullmatch(line)):
            live_cost = float(m.group(1))
        elif voice is None and (m := _VOICE_RE.fullmatch(line)):
            voice = m.group(1)
    if duration is None:
        return None

    stem = path.stem
    teachback = (get_teachback_dir() / f"{stem}.json").is_file()
    tutoring = teachback or (get_tutoring_dir() / f"{stem}.json").is_file()
    return {
        "stem": stem,
        "started_at": started.group(1),
        "mission": mission or "unknown",
        "duration_sec": duration,
        "completed": bool(completed),
        "voice": voice,
        "has_tutoring": tutoring,
        "kind": "teachback" if teachback else "smalltalk" if mission == SMALLTALK_MISSION else "call",
        "cost": combine_cost(live_cost, None),
    }


def live_cost_of(path: Path) -> Optional[float]:
    """전문 머리글의 Live 추정 비용(없거나 모르면 None)."""
    call = _parse_call(Path(path))
    return call["cost"]["live"] if call else None


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _tutoring_cost(call: Dict[str, Any]) -> Optional[float]:
    if not call["has_tutoring"]:
        return None
    directory = get_teachback_dir() if call["kind"] == "teachback" else get_tutoring_dir()
    data = _read_json(directory / f"{call['stem']}.json")
    return _number(data.get("cost_usd")) if data else None


def _all_calls() -> List[Dict[str, Any]]:
    """읽을 수 있는 모든 통화를 최신순으로 돌려준다."""
    directory = get_transcript_dir()
    try:
        paths = [p for p in directory.glob("*.md") if _valid_stem(p.stem)]
    except OSError as e:
        logger.warning("통화 기록 폴더를 읽지 못했어요 %s: %s", directory, e)
        return []
    calls = [c for c in (_parse_call(p) for p in sorted(paths, reverse=True)) if c]
    return calls


def list_calls(limit: int = 50) -> List[Dict[str, Any]]:
    """최신순 통화 목록. limit개까지."""
    calls = _all_calls()[: max(int(limit), 0)]
    for call in calls:
        call["cost"] = combine_cost(call["cost"]["live"], _tutoring_cost(call))
    return calls


def totals(now: Optional[datetime] = None) -> Dict[str, int]:
    """누적 합계: 통화 수, 분(초 합계의 내림), 통화한 날 수, 최근 7일 통화 수."""
    calls = _all_calls()
    cutoff = (now or datetime.now()) - timedelta(days=7)
    week = sum(1 for c in calls if datetime.strptime(c["started_at"], "%Y-%m-%d %H:%M") >= cutoff)
    return {
        "calls": len(calls),
        "minutes": sum(c["duration_sec"] for c in calls) // 60,
        "days": len({c["started_at"][:10] for c in calls}),
        "week": week,
    }


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("튜터링 결과를 읽지 못했어요 %s: %s", path, e)
        return None
    return data if isinstance(data, dict) else None


def _read_transcript(path: Path) -> List[Dict[str, str]]:
    """본문 턴을 순서대로. 이어지는 줄은 앞 턴에 붙이고, 잡음 표시를 지운 뒤 빈 턴은 버린다."""
    try:
        lines = path.read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("통화 전문을 읽지 못했어요 %s: %s", path, e)
        return []
    raw: List[List[str]] = []
    for line in lines[lines.index("") + 1 :] if "" in lines else []:
        if m := _TURN_RE.fullmatch(line):
            raw.append([m.group(1).lower(), m.group(2) or ""])
        elif raw and line.strip():
            raw[-1][1] += " " + line
    turns = [{"speaker": s, "text": " ".join(NOISE_MARK_RE.sub(" ", t).split())} for s, t in raw]
    return [t for t in turns if t["text"]]


def _read_verbatim(path: Path) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return text or None


def load_call(stem: str) -> Dict[str, Any]:
    """통화 한 건과 저장된 튜터링(없으면 None). stem이 틀리면 ValueError, 없으면 FileNotFoundError."""
    if not _valid_stem(stem):
        raise ValueError("허용되지 않은 통화 번호입니다")
    path = get_transcript_dir() / f"{stem}.md"
    if not path.is_file():
        raise FileNotFoundError("해당 통화 기록이 없습니다")
    call = _parse_call(path)
    if call is None:
        raise FileNotFoundError("통화 기록을 읽을 수 없습니다")
    directory = get_teachback_dir() if call["kind"] == "teachback" else get_tutoring_dir()
    tutoring = _read_json(directory / f"{stem}.json") if call["has_tutoring"] else None
    call["cost"] = combine_cost(call["cost"]["live"], _number(tutoring.get("cost_usd")) if tutoring else None)
    return {
        "call": call,
        "tutoring": tutoring,
        "transcript": _read_transcript(path),
        "verbatim": _read_verbatim(directory / f"{stem}.verbatim.txt"),
    }

"""GET /api/people: 사람 목록(홈)에 필요한 사람별 마지막 활동.

Ms. Park(park)과 친구 모두에 대해 마지막 통화, 마지막 채팅 메시지, 통화 수, 둘 중 더 늦은 시각(last_at)을 낸다.
숨긴 친구를 거르는 일은 하지 않는다(숨김은 화면의 표시 규칙이다). 통화도 채팅도 없으면 last_call, last_message,
last_at이 모두 null이다. 읽기 전용이다.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter

from server import chat, history
from server.partner_memory import KST, PARTNER_IDS

logger = logging.getLogger(__name__)

router = APIRouter()

PARK_ID = "park"
PREVIEW_CHARS = 120


def _call_time(started_at: str) -> Optional[datetime]:
    """전문 머리글의 "YYYY-MM-DD HH:MM"(한국 시각)을 시각으로. 형식이 틀리면 None."""
    try:
        return datetime.strptime(started_at, "%Y-%m-%d %H:%M").replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None


def _message_time(at: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(at)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=KST)


def _last_message(partner_id: str) -> Optional[Dict[str, str]]:
    try:
        messages = chat.load_messages(partner_id, 1)
    except (OSError, ValueError) as e:
        logger.warning("채팅 기록을 읽지 못했어요 %s: %s", partner_id, e)
        return None
    if not messages:
        return None
    last = messages[-1]
    return {"role": last["role"], "text": last["text"][:PREVIEW_CHARS], "at": last["at"]}


def build_people() -> List[Dict[str, Any]]:
    """park 먼저, 그 뒤에 친구 id 순서대로. 정렬은 화면이 last_at으로 한다."""
    by_partner: Dict[str, List[Dict[str, Any]]] = {}
    for call in history._all_calls():  # 최신순. 비용 계산이 필요 없어서 목록 함수 대신 쓴다.
        by_partner.setdefault(call["partner"] or PARK_ID, []).append(call)

    people: List[Dict[str, Any]] = []
    for partner_id in (PARK_ID, *PARTNER_IDS):
        calls = by_partner.get(partner_id, [])
        last_call = None
        if calls:
            c = calls[0]
            last_call = {
                "stem": c["stem"],
                "started_at": c["started_at"],
                "mission": c["mission"],
                "duration_sec": c["duration_sec"],
            }
        # 채팅은 친구만 있다. Ms. Park과는 통화로만 이야기한다.
        last_message = None if partner_id == PARK_ID else _last_message(partner_id)

        times = [t for t in (_call_time(last_call["started_at"]) if last_call else None, _message_time(last_message["at"]) if last_message else None) if t]
        people.append(
            {
                "id": partner_id,
                "last_call": last_call,
                "last_message": last_message,
                "call_count": len(calls),
                "last_at": max(times).isoformat(timespec="seconds") if times else None,
            }
        )
    return people


@router.get("/api/people")
async def people_endpoint():
    return {"people": await asyncio.to_thread(build_people)}

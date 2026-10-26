"""친구 수다 통화의 말투 지시문(VOICE STYLE) 접미사.

라이브 모델은 텍스트 태그를 받지 않으므로 사람다운 말소리는 시스템 지시문으로만 유도한다.
턴 넘기기 코드는 건드리지 않고, 통화 설정이 확정되는 자리에서 지시문 끝에 짧은 영어 블록만 붙인다.
LIVE_VOICE_STYLE=off 이면 지시문이 바이트 단위로 그대로다. 설명은 docs/voice-style.md.
"""

import logging
import os
from dataclasses import replace
from typing import Optional

from server.call_bot import CHAT_MODES, CallConfig

logger = logging.getLogger(__name__)

VOICE_STYLE_ENV = "LIVE_VOICE_STYLE"
MAX_WORDS = 120

VOICE_STYLE = (
    "VOICE STYLE (this is only how you sound; never mention these notes). "
    "About one reply in four, start with a quick reaction word such as \"Oh\", \"Gotcha\", \"Exactly\" or \"Right?\", "
    "and skip it the other times. "
    "Keep a relaxed, conversational pitch like a friend chatting: no sing-song, no big rises and falls, no exaggerated excitement. "
    "Keep your energy to the last word of each sentence instead of fading out or trailing off. "
    "Take short natural pauses between thoughts. "
    "Keep fillers like \"um\" rare. "
    "Never read stage directions, sound effects or tags aloud."
)


def enabled() -> bool:
    return os.getenv(VOICE_STYLE_ENV, "on").strip().lower() not in ("off", "0", "false", "no")


def with_voice_style(config: CallConfig, mode: Optional[str] = None) -> CallConfig:
    """친구 수다 모드(CHAT_MODES)이고 스위치가 켜져 있으면 지시문 끝에 VOICE STYLE을 붙인 설정을, 아니면 같은 설정을 돌려준다."""
    mode = config.mode if mode is None else mode
    if mode not in CHAT_MODES or not enabled() or VOICE_STYLE in config.system_instruction:
        return config
    logger.info("Voice style applied: mode=%s engine=%s partner=%s +%d words", mode, config.engine, config.partner or "park", len(VOICE_STYLE.split()))
    return replace(config, system_instruction=f"{config.system_instruction}\n\n{VOICE_STYLE}")

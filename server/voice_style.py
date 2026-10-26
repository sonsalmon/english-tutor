"""친구 수다 통화의 말투 지시문(VOICE STYLE) 접미사.

라이브 모델은 텍스트 태그를 받지 않으므로 사람다운 말소리는 시스템 지시문으로만 유도한다.
턴 넘기기 코드는 건드리지 않고, 통화 설정이 확정되는 자리에서 지시문 끝에 짧은 영어 블록만 붙인다.
LIVE_VOICE_STYLE=off 이면 지시문이 바이트 단위로 그대로다. 설명은 docs/voice-style.md.
운율 블록(PROSODY)은 따로 LIVE_PROSODY_STYLE=on 일 때만 붙는다(기본 꺼짐, 꺼지면 지시문이 이전과 같다).
"""

import logging
import os
from dataclasses import replace
from typing import Optional

from server.call_bot import CHAT_MODES, CallConfig

logger = logging.getLogger(__name__)

VOICE_STYLE_ENV = "LIVE_VOICE_STYLE"
MAX_WORDS = 120
PROSODY_STYLE_ENV = "LIVE_PROSODY_STYLE"
PROSODY_MAX_WORDS = 80

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


# 운율 블록: 형용사 대신 "어디서 무엇을 하라"는 행동으로 쓴다(H1의 형용사 지시는 음높이 폭과 말끝 하강을 못 움직였다).
# 겨냥: 이어 가는 구 끝 하강, 문장 끝 하강 비율, 새 문장 첫 음 재설정 폭, 강조 단어 돌출(.omo/dag/n5-human-voice/replica/prosody-metrics.md).
PROSODY_STYLE = (
    "PROSODY (how your sentences sound; never mention it). "
    "Use one or two sentences per reply, joined with \"and\", \"so\" or \"but\". "
    "When you pause mid-thought, keep the last word at the same pitch, as if going on. "
    "End statements at your middle pitch, not the bottom of your voice; only the final sentence may drop. "
    "Start each sentence near the pitch the last one ended on. "
    "Stress one word per sentence by lengthening it, not raising it."
)


def _switch(env: str, default: str) -> bool:
    return os.getenv(env, default).strip().lower() not in ("off", "0", "false", "no")


def enabled() -> bool:
    return _switch(VOICE_STYLE_ENV, "on")


def prosody_enabled() -> bool:
    return _switch(PROSODY_STYLE_ENV, "off")


def with_voice_style(config: CallConfig, mode: Optional[str] = None) -> CallConfig:
    """친구 수다 모드(CHAT_MODES)이면 켜진 블록(VOICE STYLE, PROSODY 순)을 지시문 끝에 붙인 설정을, 붙일 것이 없으면 같은 설정을 돌려준다."""
    mode = config.mode if mode is None else mode
    if mode not in CHAT_MODES:
        return config
    blocks = []
    if enabled() and VOICE_STYLE not in config.system_instruction:
        blocks.append(("Voice style", VOICE_STYLE))
    if prosody_enabled() and PROSODY_STYLE not in config.system_instruction:
        blocks.append(("Prosody style", PROSODY_STYLE))
    if not blocks:
        return config
    for name, text in blocks:
        logger.info("%s applied: mode=%s engine=%s partner=%s +%d words", name, mode, config.engine, config.partner or "park", len(text.split()))
    return replace(config, system_instruction=config.system_instruction + "".join(f"\n\n{text}" for _, text in blocks))

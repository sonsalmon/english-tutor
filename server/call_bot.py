"""Pipecat 통화 파이프라인 (docs/spec.md 11절).

브라우저(PipecatClient + SmallWebRTC)가 /api/offer로 연결하면 이 모듈의 run_bot이
Gemini Live(Vertex) 통화를 돌린다. 통화가 끝나면 마이크 원음 WAV를 먼저, 그다음
전문(.md)을 저장한다. /api/tutor는 .md가 생기면 곧바로 분석을 시작하므로 순서가
반대면 WAV를 못 찾는 경합이 생긴다.
"""

import asyncio
import functools
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from google.genai.types import AudioTranscriptionConfig, EndSensitivity, StartSensitivity

from server.config_utils import get_project_id
from server.engines.base import (
    ALLOWED_ENGINES,
    DEFAULT_ENGINE,
    GEMINI_38_ENGINE,
    GEMINI_ENGINES,
    LIVE_38_MODEL,
    TurnListener,
    engine_unavailable_reason,
)
from server.lesson import session_time_limit_from_env
from server import barge_in, call_tools, partner_memory
from server.audio_gain import ChainAudioFilter, InputGainFilter, input_gain_settings
from server.partner_memory import PARTNER_IDS, PARTNER_NAMES
from server.pricing import UsageTotals, estimate_cost
from server.readgloss import LEMMA_RE
from server.transcript_clean import clean_learner_text
from server.transcript_store import (
    get_transcript_dir,
    save_call_audio,
    save_transcript,
    transcript_stem,
)

logger = logging.getLogger(__name__)

MODES = ("mission", "freetalk", "teachback", "smalltalk")
PAUSE_LIMIT_ENV = "PAUSE_LIMIT_SEC"
DEFAULT_PAUSE_LIMIT_SEC = 600
MAX_INSTRUCTION_CHARS = 30_000
MIC_SAMPLE_RATE = 16_000
MIC_MAX_BYTES = MIC_SAMPLE_RATE * 2 * 60 * 30  # 16bit mono, 30분
DEFAULT_VOICE = "Puck"
OPENER_TEXT = "[The learner just joined the call. Start as Ms. Park.]"
TURN_MODE_ENV = "TURN_MODE"
DEFAULT_LIVE_MODEL = "gemini-live-2.5-flash-native-audio"
# 가벼운 대화·자유 대화(chat) 통화에만 모델·VAD 노브를 따로 준다. 미션·Teach-back은 늘 기본값.
CHAT_MODES = ("smalltalk", "freetalk")
LIVE_MODEL_ENV = "LIVE_MODEL"
LIVE_MODEL_CHAT_ENV = "LIVE_MODEL_CHAT"
VAD_CHAT_END_SENSITIVITY_ENV = "LIVE_VAD_CHAT_END_SENSITIVITY"
VAD_CHAT_SILENCE_MS_ENV = "LIVE_VAD_CHAT_SILENCE_MS"
VAD_CHAT_PREFIX_MS_ENV = "LIVE_VAD_CHAT_PREFIX_MS"
VAD_PREFIX_MS_MAX = 2000
# 말 시작 민감도(모든 통화 모드): 숨소리·잡음에 친구 말이 멈추지 않게 LOW, 앞 여유 500ms가 기본이다(2026-10-21).
VAD_START_SENSITIVITY_ENV = "LIVE_VAD_START_SENSITIVITY"
VAD_PREFIX_MS_ENV = "LIVE_VAD_PREFIX_MS"
DEFAULT_VAD_START_SENSITIVITY = "LOW"
DEFAULT_VAD_PREFIX_MS = 500
# 입력 오디오 잡음 제거(RNNoise, 무료). NOISE_FILTER=off면 끈다.
NOISE_FILTER_ENV = "NOISE_FILTER"
# 상대가 말하는 동안 학습자가 맞장구가 아닌 낱말을 이만큼 말해야 상대 말을 끊는다(2026-10-24).
# Gemini는 말 시작만 듣고 끊어서 "uh-huh"·길거리 목소리에도 멈췄다. 0이면 옛 방식(Gemini가 끊음).
# 대답 없음 진단 로그: 상대가 말을 끝낸 뒤 8초가 지나도 다음 대답이 없으면 5초마다 마이크 크기를 남긴다(최대 2분).
WAIT_LOG_START_SEC = 8
WAIT_LOG_EVERY_SEC = 5
WAIT_LOG_MAX_SEC = 120
WAIT_LOUD_PEAK = 600  # 약 -35 dBFS: 이보다 크면 말소리나 또럷한 잡음
# 화면 안내(2026-10-25, 통화 화면 2·3번). 같은 대기 감시에서 작은 RTVI 서버 메시지를 보낸다.
# 생각 중: 학습자가 말한 뒤(큰 프레임 THINK_MIN_VOICE_FRAMES개 이상) 조용해진 지 THINK_AFTER_SEC가 지나도 대답이 없으면.
THINK_AFTER_SEC = 2.5
THINK_MIN_VOICE_FRAMES = 10
# 마이크 작음: 낱말 QUIET_MIN_WORDS개 이상 받아쓴 말의 소리 최대치가 QUIET_PEAK(약 -24 dBFS) 아래인 일이 연달아 QUIET_STREAK번.
QUIET_PEAK = 2000
QUIET_MIN_WORDS = 3
QUIET_STREAK = 2
# 잡음 큼: 대답 없음 진단 로그 때 큰 프레임이 NOISY_LOUD_PCT% 이상이면(말에는 쉬는 틈이 있어 그렇게 꽉 차지 않는다).
NOISY_LOUD_PCT = 90
MIC_CLEAR_LOUD_PCT = 50
BARGE_IN_WORDS_ENV = "LIVE_BARGE_IN_WORDS"
DEFAULT_BARGE_IN_WORDS = 3
# 끼어들기 방식(묶음 4 P1): vad = 로컬 Silero 게이트 + 낱말 보조(기본), words = 낱말만(옛 동작), native = Gemini 기본 끊기.
BARGE_IN_MODE_ENV = "LIVE_BARGE_IN_MODE"
BARGE_IN_MODES = ("vad", "words", "native")
DEFAULT_BARGE_IN_MODE = "vad"
BARGE_IN_MIN_VOICED_MS_ENV = "LIVE_BARGE_IN_MIN_VOICED_MS"
BARGE_IN_CONFIDENCE_ENV = "LIVE_BARGE_IN_CONFIDENCE"
BARGE_IN_MIN_DBFS_ENV = "LIVE_BARGE_IN_MIN_DBFS"
# 침묵 재참여(묶음 4 P4): 학습자가 이만큼 조용하면 상대가 먼저 내용 있는 말을 꺼낸다. 0이면 끈다.
SILENCE_REENGAGE_SEC_ENV = "LIVE_SILENCE_REENGAGE_SEC"
SILENCE_REENGAGE_MAX_ENV = "LIVE_SILENCE_REENGAGE_MAX"
DEFAULT_SILENCE_REENGAGE_SEC = 10
DEFAULT_SILENCE_REENGAGE_MAX = 2
# 묶음 4 P3 A/B 전용: 선제 오디오(proactive_audio)를 끄면 모델이 대답하지 않을 자유가 사라진다. 기본 on = 옛 동작 그대로.
PROACTIVE_AUDIO_ENV = "LIVE_PROACTIVE_AUDIO"
SILENCE_NOTE_PREFIX = "[Silence note:"
LEARNER_VOICE_MS = 300  # 침묵 감시가 학습자 말로 치는 최소 유성음 길이
BARGE_IN_WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
BACKCHANNEL_WORDS = frozenset({
    "mm", "mmm", "mhm", "mm-hm", "mm-hmm", "hm", "hmm", "uh", "um", "uh-huh", "ah", "oh", "aha",
    "yeah", "yes", "yep", "yup", "ok", "okay", "right", "sure", "wow", "nice", "cool", "really",
    "음", "어", "응", "네", "아", "오",
})
VAD_SILENCE_MS_RANGE = (100, 3000)
CHAT_DEFAULT_SILENCE_MS = 500  # next10 실험 결정: 채팅 기본 end=HIGH, silence 500ms
# LIVE_MODEL·LIVE_AFFECTIVE_DIALOG는 gemini-3.8-live 시험(next10)을 위해 남긴 노브다. 둘 다 기본은 꺼져 있다
# (LIVE_MODEL 미지정 = 기본 2.5 모델, 감정 대화는 켠 상태 유지). 3.8을 쓰지 않는 한 건드리지 않는다.
AFFECTIVE_DIALOG_ENV = "LIVE_AFFECTIVE_DIALOG"  # 0|false|off면 끈다(gemini-3.8-live는 1007로 거부, 2026-10-20 확인)
MISSION_RE = re.compile(r'trying to:\s*"([^"]+)"')
MIN_LEARNER_WORDS = 3
LESSON_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)
MAX_PRACTICE_WORDS = 10
# Gemini 입력 받아쓰기가 잡음을 `{}`로 내보낼 때가 있다(2026-10-20 브라우저 시험: "{} hi, I'm ...").
NOISE_MARK_RE = re.compile(r"\{\s*\}")
# 입력 전사 언어 힌트(쉼표 구분 BCP-47). 빈 문자열이면 힌트를 넣지 않는다(Vertex가 거부할 때 끄는 스위치).
LIVE_INPUT_LANGUAGES_ENV = "LIVE_INPUT_LANGUAGES"
DEFAULT_LIVE_INPUT_LANGUAGES = "en-US,ko-KR"
SHARE_FETCH_TIMEOUT_SEC = 25
NOT_YET_RESULT = {
    "status": "ignored",
    "reason": "The learner has not practiced yet in this call. Do not end the mission. Keep the conversation going.",
}

COMPLETE_MISSION_DESCRIPTION = (
    "Call this tool when the user has successfully completed the mission objective. "
    "Provide a score and feedback."
)
COMPLETE_MISSION_PROPERTIES = {
    "score": {
        "type": "integer",
        "description": (
            "Rating from 1 to 3 based on performance: 1 (Tiro) = Struggled or needed many hints. "
            "2 (Proficiens) = Good, intelligible but with errors or hesitation. "
            "3 (Peritus) = Excellent, fluent, no help needed."
        ),
    },
    "feedback_pointers": {
        "type": "array",
        "items": {"type": "string"},
        "description": "List of 3 constructive feedback points, written as the instructions say.",
    },
}


def live_model_for(mode: str, env=None, engine: str = DEFAULT_ENGINE) -> str:
    """통화 모드에 쓸 Live 모델. smalltalk·freetalk은 `LIVE_MODEL_CHAT`, 나머지는 `LIVE_MODEL`,
    둘 다 없으면 `MODEL`(없으면 기본 모델). 엔진 `gemini_live_38`은 환경 변수와 상관없이 그 통화만 3.8 모델이다."""
    if engine == GEMINI_38_ENGINE:
        return LIVE_38_MODEL
    env = os.environ if env is None else env
    base = env.get("MODEL") or DEFAULT_LIVE_MODEL
    key = LIVE_MODEL_CHAT_ENV if mode in CHAT_MODES else LIVE_MODEL_ENV
    return (env.get(key) or "").strip() or base


def affective_dialog_from_env(env=None, engine: str = DEFAULT_ENGINE) -> bool:
    """감정 대화(enable_affective_dialog). 기본 켬, `LIVE_AFFECTIVE_DIALOG=0|false|off|no`면 끈다.
    엔진 `gemini_live_38`은 3.8이 거부(1007)하므로 항상 끈다."""
    if engine == GEMINI_38_ENGINE:
        return False
    env = os.environ if env is None else env
    return (env.get(AFFECTIVE_DIALOG_ENV) or "").strip().lower() not in ("0", "false", "off", "no")


def chat_vad_overrides(mode: str, env=None) -> dict:
    """smalltalk·freetalk에만 적용할 Gemini VAD 노브. 값이 잘못되면 그 노브만 무시한다(통화는 계속).

    키: end_sensitivity(EndSensitivity), silence_duration_ms(int), prefix_padding_ms(int).
    환경 변수가 없으면 smalltalk만 end=HIGH, silence_ms=500(next10 실험 결정)이고, freetalk은 기존 기본값
    (end=LOW, 1200ms)을 그대로 쓴다(빈 dict). 환경 변수는 두 채팅 모드 모두에 적용된다. 앞 여유(prefix)는 기본 VAD 그대로다.
    TURN_MODE=smart(Gemini VAD 끔)이면 비어 있다.

    되돌리기 한 줄(smalltalk도 옛 값으로): LIVE_VAD_CHAT_END_SENSITIVITY=LOW LIVE_VAD_CHAT_SILENCE_MS=1200
    이유: 새 기본값의 근거가 설정당 유효 통화 2건뿐이고, 말 사이 멈춤이 긴 freetalk은 학습자가 잘릴 위험이 커서 제외했다."""
    env = os.environ if env is None else env
    if mode not in CHAT_MODES or env.get(TURN_MODE_ENV, "gemini") == "smart":
        return {}
    out: dict = {}
    if mode == "smalltalk":
        out = {
            "end_sensitivity": EndSensitivity.END_SENSITIVITY_HIGH,
            "silence_duration_ms": CHAT_DEFAULT_SILENCE_MS,
        }
    raw = (env.get(VAD_CHAT_END_SENSITIVITY_ENV) or "").strip().upper()
    if raw in ("HIGH", "LOW"):
        out["end_sensitivity"] = getattr(EndSensitivity, f"END_SENSITIVITY_{raw}")
    elif raw:
        logger.warning("%s=%r ignored (HIGH|LOW)", VAD_CHAT_END_SENSITIVITY_ENV, raw)
    for key, name, low, high in (
        ("silence_duration_ms", VAD_CHAT_SILENCE_MS_ENV, VAD_SILENCE_MS_RANGE[0], VAD_SILENCE_MS_RANGE[1]),
        ("prefix_padding_ms", VAD_CHAT_PREFIX_MS_ENV, 0, VAD_PREFIX_MS_MAX),
    ):
        raw = (env.get(name) or "").strip()
        if not raw:
            continue
        try:
            value = int(raw)
        except ValueError:
            value = None
        if value is None or value < low or (high is not None and value > high):
            logger.warning("%s=%r ignored (int %s..%s)", name, raw, low, high if high is not None else "")
            continue
        out[key] = value
    return out


def start_vad_settings(env=None) -> dict:
    """모든 통화 모드에 적용할 Gemini VAD의 말 시작 노브. 기본 start=LOW, prefix_padding_ms=500.

    `LIVE_VAD_START_SENSITIVITY`(HIGH|LOW)·`LIVE_VAD_PREFIX_MS`(0..2000)로 바꾼다. 잘못된 값은 경고만 남기고 기본값을 쓴다.
    되돌리기 한 줄(옛 값): LIVE_VAD_START_SENSITIVITY=HIGH LIVE_VAD_PREFIX_MS=300"""
    env = os.environ if env is None else env
    sensitivity = DEFAULT_VAD_START_SENSITIVITY
    raw = (env.get(VAD_START_SENSITIVITY_ENV) or "").strip().upper()
    if raw in ("HIGH", "LOW"):
        sensitivity = raw
    elif raw:
        logger.warning("%s=%r ignored (HIGH|LOW)", VAD_START_SENSITIVITY_ENV, raw)
    prefix = DEFAULT_VAD_PREFIX_MS
    raw = (env.get(VAD_PREFIX_MS_ENV) or "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = None
        if value is None or not 0 <= value <= VAD_PREFIX_MS_MAX:
            logger.warning("%s=%r ignored (int 0..%s)", VAD_PREFIX_MS_ENV, raw, VAD_PREFIX_MS_MAX)
        else:
            prefix = value
    return {
        "start_sensitivity": getattr(StartSensitivity, f"START_SENSITIVITY_{sensitivity}"),
        "prefix_padding_ms": prefix,
    }


def barge_in_words_from_env(env=None) -> int:
    """`LIVE_BARGE_IN_WORDS`(0 이상 정수). 없거나 잘못되면 기본 3. 0이면 Gemini 기본 끊기(옛 방식)."""
    raw = ((os.environ if env is None else env).get(BARGE_IN_WORDS_ENV) or "").strip()
    if not raw:
        return DEFAULT_BARGE_IN_WORDS
    try:
        value = int(raw)
    except ValueError:
        value = -1
    if value < 0:
        logger.warning("%s=%r ignored (int >= 0)", BARGE_IN_WORDS_ENV, raw)
        return DEFAULT_BARGE_IN_WORDS
    return value


def barge_in_mode_from_env(env=None) -> str:
    """`LIVE_BARGE_IN_MODE`(vad|words|native). 없거나 잘못되면 기본 vad."""
    raw = ((os.environ if env is None else env).get(BARGE_IN_MODE_ENV) or "").strip().lower()
    if not raw:
        return DEFAULT_BARGE_IN_MODE
    if raw not in BARGE_IN_MODES:
        logger.warning("%s=%r ignored (%s)", BARGE_IN_MODE_ENV, raw, "|".join(BARGE_IN_MODES))
        return DEFAULT_BARGE_IN_MODE
    return raw


def _number_env(env, name: str, default, low, high, cast):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        value = None
    if value is None or not low <= value <= high:
        logger.warning("%s=%r ignored (%s..%s)", name, raw, low, high)
        return default
    return value


def barge_in_gate_settings(env=None) -> dict:
    """BargeInGate 생성자 인자: 최소 유성음 길이(ms), Silero 신뢰도, 최소 레벨(dBFS). 잘못된 값은 그 노브만 무시."""
    env = os.environ if env is None else env
    return {
        "min_voiced_ms": _number_env(env, BARGE_IN_MIN_VOICED_MS_ENV, barge_in.DEFAULT_MIN_VOICED_MS, 200, 3000, int),
        "confidence": _number_env(env, BARGE_IN_CONFIDENCE_ENV, barge_in.DEFAULT_CONFIDENCE, 0.1, 0.99, float),
        "min_dbfs": _number_env(env, BARGE_IN_MIN_DBFS_ENV, barge_in.DEFAULT_MIN_DBFS, -80.0, 0.0, float),
    }


def silence_reengage_from_env(env=None) -> Tuple[int, int]:
    """(침묵 재참여 대기 초, 연속 최대 횟수). 대기 초가 0이면 끈다. 기본 (10, 2)."""
    env = os.environ if env is None else env
    return (
        _number_env(env, SILENCE_REENGAGE_SEC_ENV, DEFAULT_SILENCE_REENGAGE_SEC, 0, 300, int),
        _number_env(env, SILENCE_REENGAGE_MAX_ENV, DEFAULT_SILENCE_REENGAGE_MAX, 0, 10, int),
    )


def proactive_audio_from_env(env=None) -> bool:
    """`LIVE_PROACTIVE_AUDIO`(on|off). 없거나 잘못되면 기본 on(옛 동작). A/B 시험 전용 노브."""
    raw = ((os.environ if env is None else env).get(PROACTIVE_AUDIO_ENV) or "").strip().lower()
    if not raw or raw == "on":
        return True
    if raw == "off":
        return False
    logger.warning("%s=%r ignored (on|off)", PROACTIVE_AUDIO_ENV, raw)
    return True


def silence_prompt(seconds: int) -> str:
    return (
        f"{SILENCE_NOTE_PREFIX} the learner has said nothing for {seconds} seconds. Do not ask whether they are there "
        "and do not repeat your question. Add one or two sentences of your own on the current topic - a small story "
        "or your opinion - and end with a statement, not a question. Under 30 words.]"
    )


def call_knobs_summary(mode: str, env=None) -> str:
    """전문 메타 `- vad:` 줄 끝에 덧붙일, 이번 통화에 켜진 묶음 4 장치. 전부 꺼져 있으면 빈 문자열."""
    parts = []
    barge = barge_in_mode_from_env(env)
    if barge != "words":
        parts.append(f"barge={barge}")
    if input_gain_settings(env) is not None:
        parts.append("gain=auto")
    sec, _ = silence_reengage_from_env(env)
    if sec and mode in CHAT_MODES:
        parts.append(f"reengage={sec}s")
    return " ".join(parts)


def count_barge_in_words(text: str) -> int:
    """끼어들기로 셀 낱말 수. 맞장구(uh-huh, yeah, 음 …)와 잡음 표시 `{}`는 세지 않는다."""
    words = BARGE_IN_WORD_RE.findall(NOISE_MARK_RE.sub(" ", text or "").lower().replace("’", "'"))
    return sum(1 for word in words if word not in BACKCHANNEL_WORDS)


def noise_filter_enabled(env=None) -> bool:
    """잡음 제거 필터는 기본 켬. `NOISE_FILTER=off|0|false|no`면 끈다."""
    env = os.environ if env is None else env
    return (env.get(NOISE_FILTER_ENV) or "").strip().lower() not in ("off", "0", "false", "no")


def build_audio_in_filter(env=None):
    """TransportParams(audio_in_filter=...)에 넣을 입력 필터. 입력 이득(LIVE_INPUT_GAIN) → RNNoise 순서로 건다.
    둘 다 꺼져 있으면 None, 하나만 켜져 있으면 그 필터 그대로(LIVE_INPUT_GAIN=off이면 옛 동작과 같다)."""
    filters = []
    gain = input_gain_settings(env)
    if gain is None:
        logger.info("Input gain off (%s)", "LIVE_INPUT_GAIN")
    else:
        filters.append(InputGainFilter(**gain))
    noise = build_noise_filter(env)
    if noise is not None:
        filters.append(noise)
    if not filters:
        return None
    return filters[0] if len(filters) == 1 else ChainAudioFilter(filters)


def build_noise_filter(env=None):
    """RNNoiseFilter. 꺼져 있거나 pyrnnoise가 없으면 None(경고만, 통화는 계속)."""
    if not noise_filter_enabled(env):
        logger.info("Noise filter off (%s)", NOISE_FILTER_ENV)
        return None
    try:
        import pyrnnoise  # noqa: F401  pipecat은 없어도 import가 통과하므로 먼저 확인한다
        from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter

        noise_filter = RNNoiseFilter()
        logger.info("Noise filter on (RNNoise)")
        return noise_filter
    except Exception as exc:  # ImportError뿐 아니라 네이티브 라이브러리 로딩 실패도 통화를 막지 않는다
        logger.warning("RNNoise unavailable, running without noise filter: %s", exc)
        return None


def vad_summary(overrides: dict) -> Optional[str]:
    """전문 메타 `- vad:` 줄에 적을 요약. 적용한 노브가 없으면 None."""
    parts = []
    if "end_sensitivity" in overrides:
        parts.append("end=" + overrides["end_sensitivity"].name.removeprefix("END_SENSITIVITY_"))
    if "silence_duration_ms" in overrides:
        parts.append(f"silence_ms={overrides['silence_duration_ms']}")
    if "prefix_padding_ms" in overrides:
        parts.append(f"prefix_ms={overrides['prefix_padding_ms']}")
    return " ".join(parts) or None


def time_limit_for_mode(mode: Optional[str], env=None) -> Optional[int]:
    """통화 모드별 서버 제한 시간(초). 친구 통화(smalltalk)는 제한이 없어 None이다.

    나머지는 `SESSION_TIME_LIMIT`(기본 180), `TEACHBACK_TIME_LIMIT`(기본 900)을 따른다.
    """
    if mode == "smalltalk":
        return None
    return session_time_limit_from_env("teachback" if mode == "teachback" else None, env)


# pipecat Gemini Live 서비스가 재연결을 포기할 때 ErrorFrame에 담는 문장(MAX_CONSECUTIVE_FAILURES).
GAVE_UP_MARK = "Max consecutive failures"


TELEMETRY_NUM_KEYS = ("t", "rtt", "out_pk", "out_kb", "in_pk", "in_lost", "in_jit", "in_kb", "jbuf", "rin_lost", "rin_jit", "paused", "rd")
TELEMETRY_STR_KEYS = ("vis", "ice", "conn", "dc", "pair", "net", "mic", "dead")
TELEMETRY_STR_RE = re.compile(r"[A-Za-z0-9_/.\-]{1,24}")


def format_telemetry(data: Any) -> Optional[str]:
    """브라우저가 5초마다 보내는 연결 품질 묶음을 로그 한 줄로 만든다. 알려진 항목만, 숫자와 짧은 영문 낱말만 싣는다."""
    if not isinstance(data, dict):
        return None
    parts = []
    for key in TELEMETRY_STR_KEYS:
        value = data.get(key)
        if isinstance(value, str) and TELEMETRY_STR_RE.fullmatch(value):
            parts.append(f"{key}={value}")
    for key in TELEMETRY_NUM_KEYS:
        value = data.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and abs(value) < 1e12:
            parts.append(f"{key}={int(value) if float(value).is_integer() else round(value, 1)}")
    return " ".join(parts) or None


def llm_gave_up(error_text: Any) -> bool:
    """Gemini 연결을 되살리지 못해 이 통화는 더 이어 갈 수 없는 오류인지."""
    return GAVE_UP_MARK in str(error_text or "")


def pause_limit_from_env(env=None) -> int:
    """일시정지를 이 시간(초)보다 오래 두면 통화를 끝낸다. `PAUSE_LIMIT_SEC`(기본 600)."""
    env = os.environ if env is None else env
    return int(env.get(PAUSE_LIMIT_ENV, str(DEFAULT_PAUSE_LIMIT_SEC)))


class CallClock:
    """통화 경과 시간. 일시정지 동안은 흐르지 않고, 일시정지 자체의 길이도 잰다."""

    def __init__(self, now=time.monotonic):
        self._now = now
        self._started: Optional[float] = None
        self._paused_at: Optional[float] = None
        self._paused_total = 0.0

    def start(self) -> None:
        self._started = self._now()
        self._paused_at = None
        self._paused_total = 0.0

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def pause(self) -> bool:
        """일시정지한다. 시작 전이거나 이미 멈춰 있으면 False."""
        if self._started is None or self.paused:
            return False
        self._paused_at = self._now()
        return True

    def resume(self) -> bool:
        """다시 시작한다. 멈춰 있지 않으면 False."""
        if not self.paused:
            return False
        self._paused_total += self._now() - self._paused_at
        self._paused_at = None
        return True

    def paused_for(self) -> float:
        """지금 일시정지가 이어진 시간(멈춰 있지 않으면 0)."""
        return self._now() - self._paused_at if self.paused else 0.0

    def paused_total(self) -> float:
        """통화 동안 일시정지한 총 시간(지금 멈춰 있는 시간 포함)."""
        return self._paused_total + self.paused_for()

    def elapsed(self) -> float:
        """일시정지를 뺀 통화 경과 시간."""
        if self._started is None:
            return 0.0
        return self._now() - self._started - self.paused_total()

    def check(self, time_limit: Optional[float], pause_limit: float) -> Tuple[Optional[str], Optional[float]]:
        """(끝낼 이유, 다음 확인까지 기다릴 초). 이유는 "time_limit"·"pause_limit"·None.

        time_limit이 None이면 시간 제한이 없다: 멈추지 않은 동안은 기다릴 시간도 None(변화가 올 때까지)이다.
        """
        if self.paused:
            wait = pause_limit - self.paused_for()
            return ("pause_limit", 0.0) if wait <= 0 else (None, wait)
        if time_limit is None:
            return (None, None)
        wait = time_limit - self.elapsed()
        return ("time_limit", 0.0) if wait <= 0 else (None, wait)


@dataclass(frozen=True)
class CallConfig:
    system_instruction: str
    mode: str
    voice: str = DEFAULT_VOICE
    partner: Optional[str] = None
    # 통화가 끝난 뒤 서버가 스스로 정리를 걸 때 쓰는 입력(예전에는 화면이 /api/tutor 본문으로 보냈다).
    lesson_date: Optional[str] = None
    practice_words: Tuple[str, ...] = ()
    # 자동으로 다시 건 통화면 화면이 들고 있던 직전 대화(화자 "Me"/"Partner", 글). 직전 전문이 아직 저장되지 않았어도 이어 갈 수 있게 한다.
    resume_turns: Tuple[Tuple[str, str], ...] = ()
    # 통화 엔진(docs/engines.md). 기본 gemini_live는 오늘 아침 동작과 같다.
    engine: str = DEFAULT_ENGINE

    @property
    def mission(self) -> Optional[str]:
        return mission_title(self.system_instruction)

    @property
    def opener(self) -> bool:
        # Teach-back은 학생 Maya가 지시문대로 시작하고, 학습자가 먼저 말한다.
        return self.mode != "teachback"

    @property
    def time_limit(self) -> Optional[int]:
        return time_limit_for_mode(self.mode)


PARTNER_MEMORY_MODES = ("smalltalk", "freetalk")
MAX_RESUME_TURNS = 12
MAX_RESUME_TURN_CHARS = 1000


def opener_text(partner: Optional[str]) -> str:
    """통화 시작 때 모델에 보내는 첫 사용자 메시지. 친구 통화면 그 친구 이름으로 시작하게 한다."""
    name = PARTNER_NAMES.get(partner or "", "Ms. Park")
    return f"[The learner just joined the call. Start as {name}.]"


# 이미 친구 기억 갱신을 걸어 둔 통화 전문 파일명(통화당 한 번, 실패하면 다시 걸 수 있게 뺀다).
_PARTNER_UPDATED: "set[str]" = set()
_background_tasks: "set[asyncio.Task]" = set()


def update_partner_memory_sync(partner_id: str, turns: List[Tuple[str, str]], source: Optional[str] = None) -> bool:
    from server.tutor import make_generate_text

    return partner_memory.update(partner_id, turns, generate_text=make_generate_text(), source=source)


def schedule_partner_memory_update(saved: Any, config: "CallConfig", record: "CallRecord") -> Optional[asyncio.Task]:
    """저장된 통화가 친구 통화이고 학습자 발화가 있으면 이 통화의 턴만으로 기억 갱신을 뒤에서 돌린다. 걸지 않으면 None."""
    if not config.partner or saved is None:
        return None
    turns = [(speaker, text) for speaker, text in record.chunks if speaker in ("Me", "Partner")]
    if not any(speaker == "Me" and text.strip() for speaker, text in turns):
        return None
    key = getattr(saved, "name", str(saved))
    if key in _PARTNER_UPDATED:
        return None
    _PARTNER_UPDATED.add(key)
    partner_id = config.partner

    async def _run():
        try:
            if await asyncio.to_thread(update_partner_memory_sync, partner_id, turns, getattr(saved, "stem", None)):
                logger.info("Partner memory updated: %s", partner_id)
                return
        except Exception as e:  # noqa: BLE001
            logger.error("Partner memory update failed: %s", e)
        _PARTNER_UPDATED.discard(key)  # 실패: 나중에 다시 걸 수 있다

    task = asyncio.create_task(_run())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def mission_title(instruction: str) -> Optional[str]:
    match = MISSION_RE.search(instruction or "")
    return match.group(1) if match else None


def parse_call_config(data: Any) -> CallConfig:
    """브라우저가 /api/offer의 request_data로 보낸 통화 설정을 검사한다. 틀리면 ValueError."""
    if not isinstance(data, dict):
        raise ValueError("통화 설정(request_data)이 없습니다.")
    instruction = data.get("system_instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("system_instruction이 비었습니다.")
    if len(instruction) > MAX_INSTRUCTION_CHARS:
        raise ValueError(f"system_instruction이 {MAX_INSTRUCTION_CHARS}자를 넘습니다.")
    mode = data.get("mode", "mission")
    if mode not in MODES:
        raise ValueError(f"mode는 {MODES} 중 하나여야 합니다.")
    voice = data.get("voice") or DEFAULT_VOICE
    if not isinstance(voice, str) or not voice.isalpha():
        raise ValueError("voice 이름이 올바르지 않습니다.")
    engine = data.get("engine") or DEFAULT_ENGINE
    if engine not in ALLOWED_ENGINES:
        raise ValueError(f"engine은 {ALLOWED_ENGINES} 중 하나여야 합니다.")
    if engine != DEFAULT_ENGINE:
        if mode != "smalltalk":
            raise ValueError("실험 엔진은 친구 수다 통화에만 쓸 수 있습니다.")
        reason = engine_unavailable_reason(engine)
        if reason:
            raise ValueError(reason)
    partner = data.get("partner")
    # 기억은 수다·자유 대화만 쓴다: 미션 역할극 발화는 학습자의 실제 사실이 아니다.
    if partner not in PARTNER_IDS or mode not in PARTNER_MEMORY_MODES:
        partner = None
    lesson_date = data.get("lesson_date")
    if lesson_date is not None:
        try:
            if not isinstance(lesson_date, str) or not LESSON_DATE_RE.fullmatch(lesson_date):
                raise ValueError
            datetime.strptime(lesson_date, "%Y-%m-%d")
        except ValueError:
            raise ValueError("lesson_date는 YYYY-MM-DD 형식이어야 합니다.") from None
    raw_words = data.get("practice_words")
    practice_words = tuple(
        w for w in (raw_words[:MAX_PRACTICE_WORDS] if isinstance(raw_words, list) else []) if isinstance(w, str) and LEMMA_RE.fullmatch(w)
    )
    raw_turns = data.get("resume_turns")
    resume_turns = tuple(
        ("Me" if t.get("who") == "me" else "Partner", " ".join(t["text"].split())[:MAX_RESUME_TURN_CHARS])
        for t in (raw_turns[-MAX_RESUME_TURNS:] if isinstance(raw_turns, list) else [])
        if isinstance(t, dict) and isinstance(t.get("text"), str) and t["text"].strip()
    )
    return CallConfig(
        system_instruction=instruction,
        mode=mode,
        voice=voice,
        partner=partner,
        lesson_date=lesson_date,
        practice_words=practice_words,
        resume_turns=resume_turns,
        engine=engine,
    )


@dataclass
class CallRecord:
    started_at: float = field(default_factory=time.time)
    chunks: List[Tuple[str, str]] = field(default_factory=list)
    mic_pcm: bytearray = field(default_factory=bytearray)
    completed: bool = False
    paused_sec: float = 0.0
    usage: UsageTotals = field(default_factory=UsageTotals)

    def add_user(self, text: str) -> None:
        if (text or "").lstrip().startswith(SILENCE_NOTE_PREFIX):
            return  # 3.8이 침묵 재참여 메모를 학습자 말로 받아쓸 수 있다
        clean = clean_learner_text(" ".join(NOISE_MARK_RE.sub(" ", text or "").split()))
        if clean:
            self.chunks.append(("Me", clean))

    def add_partner(self, text: str) -> None:
        if text and text.strip():
            self.chunks.append(("Partner", text.strip()))

    def add_note(self, speaker: str, text: str) -> None:
        """공유한 링크·장면처럼 말이 아닌 기록. 전문에 `**<speaker>:** ...`로 남는다."""
        if text and text.strip():
            self.chunks.append((speaker, " ".join(text.split())))

    def learner_has_spoken(self) -> bool:
        # 학습자가 실제로 말하기 전에 모델이 미션을 끝내면 학습자 카드 예문을 이번 발화처럼 인용한 적이 있다(2026-10-20 브라우저 시험).
        return sum(len(text.split()) for speaker, text in self.chunks if speaker == "Me") >= MIN_LEARNER_WORDS

    def add_mic(self, pcm: bytes) -> None:
        room = MIC_MAX_BYTES - len(self.mic_pcm)
        if room > 0:
            self.mic_pcm.extend(pcm[:room])


def add_usage_metrics(usage: UsageTotals, data: Any) -> None:
    """Pipecat MetricsFrame.data 안의 LLM 토큰 사용량(LLMUsageMetricsData)만 통화 합계에 더한다.

    Gemini Live는 턴마다 그 턴에 청구되는 전체 문맥 토큰을 보고하므로 더하기만 하면 된다.
    """
    for item in data or []:
        tokens = getattr(item, "value", None)
        if hasattr(tokens, "prompt_tokens") and hasattr(tokens, "completion_tokens"):
            usage.add_tokens(
                tokens.prompt_tokens,
                tokens.completion_tokens,
                getattr(tokens, "input_audio_tokens", None),
                getattr(tokens, "output_audio_tokens", None),
            )


def make_usage_collector(usage: UsageTotals):
    """LLM 서비스 뒤에 두는 처리기: 지나가는 MetricsFrame의 토큰 사용량을 usage에 더하고 프레임은 그대로 흘린다."""
    from pipecat.frames.frames import Frame, MetricsFrame
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    class UsageCollector(FrameProcessor):
        async def process_frame(self, frame: Frame, direction: FrameDirection):
            await super().process_frame(frame, direction)
            if isinstance(frame, MetricsFrame):
                add_usage_metrics(usage, frame.data)
            await self.push_frame(frame, direction)

    return UsageCollector()


def job_spec_for(config: "CallConfig"):
    """통화 정리 작업의 입력(mode·수업 날짜·연습 단어)."""
    from server.summary_jobs import JobSpec

    return JobSpec(mode=config.mode, lesson_date=config.lesson_date, practice_words=config.practice_words)


def finish_call(record: CallRecord, config: CallConfig, model: str, ended_at: Optional[float] = None, vad: Optional[str] = None):
    ended_at = ended_at or time.time()
    started_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.started_at))
    if _call_saved_hook is not None and record.learner_has_spoken():
        # 전문(.md)이 생기는 순간부터 /api/tutor·/api/calls가 이 통화를 볼 수 있으므로, 정리 입력을 그보다 먼저 남겨 둔다.
        from server.summary_jobs import write_spec

        write_spec(transcript_stem(started_str), job_spec_for(config))
    try:
        if record.mic_pcm:
            save_call_audio(bytes(record.mic_pcm), transcript_stem(started_str), sample_rate=MIC_SAMPLE_RATE)
    except Exception as e:  # noqa: BLE001 - 원음 저장 실패가 전문 저장을 막지 않는다
        logger.error("Call audio save failed: %s", e)
    try:
        saved = save_transcript(
            record.chunks,
            {
                "started_at": started_str,
                "duration_sec": max(0, int(ended_at - record.started_at - record.paused_sec)),
                "model": model,
                "voice": config.voice,
                "partner": config.partner,
                "mission": config.mission,
                "completed": record.completed,
                "cost_usd": None if record.usage.is_empty() else estimate_cost(model, record.usage),
                "vad": vad,
            },
            get_transcript_dir(),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Transcript save failed: %s", e)
        return None
    return saved


# 통화가 저장된 뒤 거는 뒷일(통화 정리). main이 시작할 때 등록한다(review.configure와 같은 방식).
_call_saved_hook: Optional[Callable[[Any, "CallConfig"], None]] = None


def configure_call_saved(hook: Optional[Callable[[Any, "CallConfig"], None]]) -> None:
    global _call_saved_hook
    _call_saved_hook = hook


# 학습자 차례마다 곁가지(조언자)를 붙이는 훅. main이 시작할 때 등록한다(configure_call_saved와 같은 방식).
# factory는 (config, record) -> TurnListener | None. None이면 그 통화는 지금과 똑같이 돈다.
_turn_listener_factory: Optional[Callable[["CallConfig", "CallRecord"], Optional[TurnListener]]] = None


def configure_turn_listener(factory: Optional[Callable[["CallConfig", "CallRecord"], Optional[TurnListener]]]) -> None:
    global _turn_listener_factory
    _turn_listener_factory = factory


def make_turn_listener(config: "CallConfig", record: "CallRecord") -> Optional[TurnListener]:
    """등록된 factory로 이 통화의 턴 리스너를 만든다. 없거나 실패하면 None(통화는 계속)."""
    if _turn_listener_factory is None:
        return None
    try:
        return _turn_listener_factory(config, record)
    except Exception as e:  # noqa: BLE001
        logger.error("Turn listener could not start: %s", e)
        return None


async def notify_turn_listener(listener: TurnListener, text: str) -> None:
    try:
        await listener.on_user_turn(text)
    except Exception as e:  # noqa: BLE001 - 조언자 실패가 통화를 막지 않는다
        logger.error("Turn listener failed: %s", e)


def notify_call_saved(saved: Any, config: "CallConfig", record: "CallRecord") -> bool:
    """저장된 통화에서 학습자가 실제로 말했으면 통화 정리를 건다. 걸었으면 True. 실패해도 통화 마무리는 막지 않는다."""
    if saved is None or _call_saved_hook is None or not record.learner_has_spoken():
        return False
    try:
        _call_saved_hook(saved, config)
    except Exception as e:  # noqa: BLE001
        logger.error("Call summary scheduling failed: %s", e)
        return False
    return True


def mission_tools(config: CallConfig):
    """미션·자유 대화에만 complete_mission 도구를 준다. Teach-back과 가벼운 대화는 점수·종료 도구 없이 진행한다(f05f290과 같음)."""
    if config.mode in ("teachback", "smalltalk"):
        return None
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema

    return ToolsSchema(standard_tools=[
        FunctionSchema(
            name="complete_mission",
            description=COMPLETE_MISSION_DESCRIPTION,
            properties=COMPLETE_MISSION_PROPERTIES,
            required=["score", "feedback_pointers"],
        )
    ])


def live_tools(config: CallConfig):
    """Teach-back을 뺀 모든 통화에 지난 통화 찾기·장면 보내기 도구를 주고, 미션·자유 대화에는 complete_mission도 더한다."""
    if config.mode == "teachback":
        return None
    from pipecat.adapters.schemas.tools_schema import ToolsSchema

    mission = mission_tools(config)
    return ToolsSchema(standard_tools=[*(mission.standard_tools if mission else []), *call_tools.tool_schemas()])


def live_config_for(mode: str, env=None, engine: str = DEFAULT_ENGINE):
    """run_bot이 쓰는 (Live 모델, Gemini VAD 설정, 로컬 사용자 설정, 전문 `- vad:` 요약)을 한 번에 돌려준다."""
    vad, user_params = turn_settings(mode, env)
    return live_model_for(mode, env, engine), vad, user_params, vad_summary(chat_vad_overrides(mode, env))


def turn_settings(mode: Optional[str] = None, env=None):
    """TURN_MODE에 따라 (Gemini VAD 설정, 로컬 VAD·Smart Turn 사용자 설정)을 돌려준다.
    mode가 smalltalk·freetalk이면 LIVE_VAD_CHAT_* 노브를 기본 VAD 위에 덮는다."""
    from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
    from pipecat.services.google.gemini_live.llm import GeminiVADParams

    env = os.environ if env is None else env
    if env.get(TURN_MODE_ENV, "gemini") == "smart":
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
        from pipecat.audio.vad.silero import SileroVADAnalyzer
        from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
        from pipecat.turns.user_turn_strategies import UserTurnStrategies

        return GeminiVADParams(disabled=True), LLMUserAggregatorParams(
            vad_analyzer=SileroVADAnalyzer(),
            user_turn_strategies=UserTurnStrategies(
                stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]
            ),
        )
    # 말 끝: 1.2초 조용해야 끝으로 본다(10-16 조정값). 말 시작은 잡음에 덜 반응하게 LOW·앞 여유 500ms(10-21).
    params = GeminiVADParams(
        end_sensitivity=EndSensitivity.END_SENSITIVITY_LOW,
        silence_duration_ms=1200,
        **start_vad_settings(env),
    )
    overrides = chat_vad_overrides(mode, env) if mode else {}
    if overrides:
        params = params.model_copy(update=overrides)
    return params, None


def live_input_languages(env=None) -> List[str]:
    raw = (os.environ if env is None else env).get(LIVE_INPUT_LANGUAGES_ENV)
    return [code.strip() for code in (DEFAULT_LIVE_INPUT_LANGUAGES if raw is None else raw).split(",") if code.strip()]


def quiet_utterance(peak: int, words: int) -> Optional[bool]:
    """받아쓴 말 하나의 소리가 작았는지. 소리 기록이 없거나 낱말이 적으면 판단하지 않는다(None)."""
    if peak <= 0 or words < QUIET_MIN_WORDS:
        return None
    return peak < QUIET_PEAK


def noisy_wait(loud_pct: int) -> Optional[bool]:
    """대답을 기다리는 동안 마이크가 계속 큰지(True), 충분히 조용한지(False), 애매한지(None)."""
    if loud_pct >= NOISY_LOUD_PCT:
        return True
    return False if loud_pct < MIC_CLEAR_LOUD_PCT else None


@functools.lru_cache(maxsize=1)
def live_service_class():
    import math

    import numpy as np
    from google.genai.types import ActivityHandling, RealtimeInputConfig
    from pipecat.frames.frames import BotStartedSpeakingFrame, BotStoppedSpeakingFrame, InputAudioRawFrame
    from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
    from pipecat.services.google.gemini_live.vertex.llm import GeminiLiveVertexLLMService

    class TranscriptHintedLiveService(GeminiLiveVertexLLMService):
        """입력 전사에 언어 힌트를 넣는다. pipecat은 힌트 없는 AudioTranscriptionConfig를 만들어 짧은 추임새를 한자로 받아쓴다.

        끼어들기(LIVE_BARGE_IN_WORDS>0, Gemini VAD 켜짐): Gemini에는 NO_INTERRUPTION을 주고, 상대가 말하는 동안
        학습자 받아쓰기에서 맞장구가 아닌 낱말이 기준 수를 넘으면 여기서 끊는다. Gemini는 그 차례를 끝까지 만들므로,
        끊은 뒤 같은 차례의 남은 음성은 turn_complete까지 버린다. 학습자 말에는 Gemini가 다음 차례에서 답한다."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._barge_in_words = 0
            self._partner_speaking = False
            self._heard_words = 0
            self._drop_rest_of_turn = False
            self._waiting_since: Optional[float] = None
            self._wait_logged_at = 0.0
            self._wait_peak = 0
            self._wait_frames = 0
            self._wait_loud = 0
        # 화면 안내(생각 중·마이크 소리) 상태. 보낼 메시지는 outbox에 쌓았다가 process_frame에서 흘려 보낸다.
        # __init__ 없이 만든 객체(테스트)에서도 돌도록 기본값은 클래스에 둔다.
        _voice_frames = 0
        _last_voice_at = 0.0
        _think_voice_mark = 0
        _thinking = False
        _utter_peak = 0
        _quiet_streak = 0
        _mic_state = "ok"
        # 끼어들기 게이트·침묵 재참여(묶음 4). 기본값은 모두 "끔".
        call_mode: Optional[str] = None
        pause_check: Optional[Callable[[], bool]] = None
        on_reengage: Optional[Callable[[int, float], None]] = None
        _analyzer = None
        _gate = None
        _voice = None
        _reengage_sec = 0
        _reengage_max = 0
        _reengage_count = 0
        _last_reengage_at = 0.0
        _last_learner_voice_at = 0.0
        _partner_first_sound_at: Optional[float] = None
        _overlap_chunks = 0

        def _queue(self, message: dict) -> None:
            self.__dict__.setdefault("_outbox", []).append(message)

        def _reset_notices(self) -> None:
            self._voice_frames = 0
            self._think_voice_mark = 0
            self._utter_peak = 0
            self._thinking = False

        def _set_thinking(self, on: bool) -> None:
            if self._thinking != on:
                self._thinking = on
                logger.info("Thinking notice: %s", "on" if on else "off")
                self._queue({"type": "thinking", "on": on})

        def _set_mic_state(self, state: str, peak: int = 0) -> None:
            if self._mic_state != state:
                self._mic_state = state
                db = round(20 * math.log10(max(peak, 1) / 32768), 1) if peak else None
                logger.info("Mic level notice: %s (peak %s dBFS)", state, db)
                self._queue({"type": "mic_level", "state": state, "db": db})

        def _check_thinking(self, loud: bool, now: float) -> None:
            if loud:
                self._voice_frames += 1
                self._last_voice_at = now
                # 생각 중이라고 알린 뒤 학습자가 다시 말하면(큰 프레임이 이어지면) 끈다.
                if self._thinking and self._voice_frames - self._think_voice_mark >= THINK_MIN_VOICE_FRAMES:
                    self._set_thinking(False)
            elif not self._thinking and self._voice_frames >= THINK_MIN_VOICE_FRAMES and now - self._last_voice_at >= THINK_AFTER_SEC:
                self._think_voice_mark = self._voice_frames
                self._set_thinking(True)

        def _check_quiet(self, text: str) -> None:
            quiet = quiet_utterance(self._utter_peak, len(BARGE_IN_WORD_RE.findall(text)))
            peak, self._utter_peak = self._utter_peak, 0
            if quiet is None:
                return
            self._quiet_streak = self._quiet_streak + 1 if quiet else 0
            if self._quiet_streak >= QUIET_STREAK:
                self._set_mic_state("quiet", peak)
            elif not quiet and self._mic_state == "quiet":
                self._set_mic_state("ok", peak)

        async def _flush_outbox(self) -> None:
            box = self.__dict__.get("_outbox")
            while box:
                await self.push_frame(RTVIServerMessageFrame(data=box.pop(0)))

        def _note_waiting_audio(self, frame) -> None:
            """상대가 말을 끝낸 뒤 다음 대답이 늦으면 마이크 크기를 주기적으로 남긴다(대답 없음 진단, 2026-10-24).
            마이크가 크면 학습자 말·잡음이 차례를 안 끝낸 것이고, 조용한데도 대답이 없으면 Gemini 쪽 지연이다."""
            if self._waiting_since is None:
                return
            samples = np.frombuffer(frame.audio, dtype=np.int16)
            now = time.monotonic()
            if samples.size:
                peak = int(np.abs(samples.astype(np.int32)).max())
                self._wait_peak = max(self._wait_peak, peak)
                self._wait_frames += 1
                self._wait_loud += peak > WAIT_LOUD_PEAK
                self._utter_peak = max(self._utter_peak, peak)
                self._check_thinking(peak > WAIT_LOUD_PEAK, now)
            if self._voice is not None and self._voice.feed(frame.audio) >= LEARNER_VOICE_MS:
                self._last_learner_voice_at = now
                self._reengage_count = 0
            waited = now - self._waiting_since
            if waited >= WAIT_LOG_START_SEC and now - self._wait_logged_at >= WAIT_LOG_EVERY_SEC and waited <= WAIT_LOG_MAX_SEC:
                db = 20 * math.log10(max(self._wait_peak, 1) / 32768)
                loud = 100 * self._wait_loud // max(self._wait_frames, 1)
                logger.info("Waiting for partner reply: %ds since partner stopped; mic peak %.0f dBFS, loud frames %d%%",
                            int(waited), db, loud)
                noisy = noisy_wait(loud)
                if noisy:
                    self._set_mic_state("noisy", self._wait_peak)
                elif noisy is False and self._mic_state == "noisy":
                    self._set_mic_state("ok", self._wait_peak)
                self._wait_logged_at, self._wait_peak, self._wait_frames, self._wait_loud = now, 0, 0, 0

        def _get_analyzer(self):
            if self._analyzer is None:
                self._analyzer = barge_in.make_analyzer()
            return self._analyzer

        def _arm_gate(self, settings: dict) -> None:
            if self._gate is None:
                try:
                    self._gate = barge_in.BargeInGate(self._get_analyzer(), **settings)
                except Exception as exc:  # noqa: BLE001 - Silero를 못 열어도 통화는 낙말 경로로 계속한다
                    logger.warning("Barge-in gate unavailable, using words only: %s", exc)
                    return
            logger.info("Barge-in gate armed (vad, %d ms)", settings["min_voiced_ms"])

        def _arm_reengage(self, seconds: int, max_count: int) -> None:
            self._reengage_sec, self._reengage_max = 0, max_count
            if not seconds or self.call_mode not in CHAT_MODES:
                return
            try:
                if self._voice is None:
                    self._voice = barge_in.VoiceRun(self._get_analyzer(), min_dbfs=None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Silence re-engage unavailable: %s", exc)
                return
            self._reengage_sec = seconds
            logger.info("Silence re-engage armed (%d s)", seconds)

        async def _gate_audio(self, frame) -> None:
            if self._gate is not None and self._partner_speaking and self._gate.feed(frame.audio):
                await self._interrupt_partner(f"{self._gate.run_ms} ms of voice while the partner speaks")

        async def _interrupt_partner(self, reason: str) -> None:
            # 생성이 아직 안 끝났으면(turn_complete 전) 같은 차례의 남은 음성이 더 온다. 보류된 turn_complete는
            # 끊기가 버리므로(_discard_deferred_turn) 그때는 버리기를 켜지 않는다(다음 대답까지 삼키지 않게).
            self._drop_rest_of_turn = self._bot_is_responding and not self._turn_complete_pending_idle
            self._partner_speaking = False
            logger.info("Barge-in: %s -> interrupt (drop rest: %s)", reason, self._drop_rest_of_turn)
            await self.broadcast_interruption()

        def _reengage_due(self, now: float) -> bool:
            """상대가 말을 끝낸 뒤 학습자가 마지막으로 말한 때(또는 직전 재참여)부터 설정한 초만큼 조용했는지."""
            if not self._reengage_sec or self._waiting_since is None:
                return False
            if self._partner_speaking or self._bot_is_responding or self._reengage_count >= self._reengage_max:
                return False
            if self.pause_check is not None and self.pause_check():
                return False
            return now - self._silence_since() >= self._reengage_sec

        def _silence_since(self) -> float:
            return max(self._waiting_since or 0.0, self._last_learner_voice_at, self._last_reengage_at)

        async def _reengage(self, now: float) -> None:
            silent = now - max(self._waiting_since or now, self._last_learner_voice_at)
            self._reengage_count += 1
            self._last_reengage_at = now
            logger.info("Silence re-engage #%d after %.1fs of silence", self._reengage_count, silent)
            if self.on_reengage is not None:
                try:
                    self.on_reengage(self._reengage_count, silent)
                except Exception as exc:  # noqa: BLE001 - 기록 실패가 통화를 막지 않는다
                    logger.error("Re-engage note failed: %s", exc)
            await self._push_prompt(silence_prompt(self._reengage_sec))

        async def send_learner_text(self, text: str) -> None:
            """학습자가 보낸 글을 Gemini 세션에 바로 넣는다. InputTextRawFrame으로 넣으면 그 프레임이 파이프라인 뒤로 흘러
            자막(bot-output)과 전문에 파트너 발화로 섞이므로 프레임을 거치지 않는다."""
            await self._send_user_text(text)

        async def _connection_task_handler(self, config):
            languages = live_input_languages()
            if languages:
                config.input_audio_transcription = AudioTranscriptionConfig(language_codes=languages)
            self._drop_rest_of_turn = False
            self._barge_in_words = 0
            ric = config.realtime_input_config
            vad_on = ric is not None and not getattr(ric.automatic_activity_detection, "disabled", False)
            words = barge_in_words_from_env()
            mode = barge_in_mode_from_env()
            gate_settings = barge_in_gate_settings()
            if vad_on and mode == "vad" and words:
                self._arm_gate(gate_settings)
            else:
                self._gate = None
            if not (vad_on and mode in ("vad", "words")):
                words = 0
            if words or self._gate is not None:
                ric.activity_handling = ActivityHandling.NO_INTERRUPTION
            if words:
                self._barge_in_words = words
                logger.info("Barge-in by words: %d (Gemini NO_INTERRUPTION)", words)
            self._arm_reengage(*silence_reengage_from_env())
            await super()._connection_task_handler(config)

        async def process_frame(self, frame, direction):
            if isinstance(frame, InputAudioRawFrame):
                self._note_waiting_audio(frame)
                await self._gate_audio(frame)
                now = time.monotonic()
                if self._reengage_due(now):
                    await self._reengage(now)
            elif isinstance(frame, BotStartedSpeakingFrame):
                self._partner_speaking = True
                self._heard_words = 0
                self._waiting_since = None
                self._partner_first_sound_at = time.monotonic()
                self._overlap_chunks = 0
                if self._gate is not None:
                    self._gate.reset()
                self._set_thinking(False)
                if self._mic_state == "noisy":
                    self._set_mic_state("ok")
            elif isinstance(frame, BotStoppedSpeakingFrame):
                self._partner_speaking = False
                self._waiting_since = time.monotonic()
                self._wait_logged_at, self._wait_peak, self._wait_frames, self._wait_loud = self._waiting_since, 0, 0, 0
                self._reset_notices()
                if self._gate is not None:
                    self._gate.reset()
                if self._voice is not None:
                    self._voice.reset()
            await super().process_frame(frame, direction)
            await self._flush_outbox()

        async def _handle_msg_input_transcription(self, message):
            await super()._handle_msg_input_transcription(message)
            text = message.server_content.input_transcription.text or ""
            # 중간 자막 가능 여부 증거(통화 화면 6번): 조각이 말하는 동안 오는지, 말이 끝난 뒤에만 오는지 마지막 큰 마이크 프레임 대비 시각을 남긴다.
            if self._last_voice_at:
                logger.info("Input chunk %r: %.1fs after the last loud mic frame (%d voice frames this turn)",
                            text, time.monotonic() - self._last_voice_at, self._voice_frames)
            if self._partner_speaking:
                self._overlap_chunks += 1
            if self._reengage_sec and not text.lstrip().startswith(SILENCE_NOTE_PREFIX) and BARGE_IN_WORD_RE.search(NOISE_MARK_RE.sub(" ", text)):
                self._reengage_count = 0
            self._check_quiet(text)
            await self._flush_outbox()
            if not (self._barge_in_words and self._partner_speaking):
                return
            self._heard_words += count_barge_in_words(text)
            if self._heard_words < self._barge_in_words:
                logger.info("Barge-in held: %r (%d/%d words)", text, self._heard_words, self._barge_in_words)
                return
            await self._interrupt_partner(f"{self._heard_words} words while the partner speaks")

        async def _handle_msg_model_turn(self, msg):
            if not self._drop_rest_of_turn:
                await super()._handle_msg_model_turn(msg)

        async def _handle_msg_output_transcription(self, message):
            if not self._drop_rest_of_turn:
                await super()._handle_msg_output_transcription(message)

        async def send_note(self, text: str) -> None:
            """감독 메모를 세션에 넣는다(turn_complete=False라 Gemini는 답하지 않고 다음 차례에 참고만 한다).
            프레임을 거치지 않아 자막·전문에 섞이지 않는다. 파트너가 말하는 중이면 그 차례가 끝난 뒤(_handle_msg_turn_complete)로 미룬다."""
            text = (text or "").strip()
            if not text:
                return
            if self._partner_speaking or self._bot_is_responding:
                self.__dict__.setdefault("_pending_notes", []).append(text)
                return
            await self._push_note(text)

        async def _push_note(self, text: str) -> None:
            if self._disconnecting or not self._session:
                return
            try:
                await self._session.send_client_content(
                    turns=[{"role": "user", "parts": [{"text": text}]}], turn_complete=False)
            except Exception as e:  # noqa: BLE001 - pipecat의 다른 전송 경로와 같은 오류 처리
                await self._handle_send_error(e)

        async def _push_prompt(self, text: str) -> None:
            """_push_note와 달리 turn_complete=True라 Gemini가 바로 이어 말한다. 침묵 재참여에만 쓴다."""
            if self._disconnecting or not self._session:
                return
            try:
                await self._session.send_client_content(
                    turns=[{"role": "user", "parts": [{"text": text}]}], turn_complete=True)
            except Exception as e:  # noqa: BLE001
                await self._handle_send_error(e)

        async def _handle_msg_turn_complete(self, message):
            if self._partner_first_sound_at is not None:
                logger.info("Turn complete: %.1fs after the partner's first sound; %d input transcript chunk(s) arrived while the partner spoke",
                            time.monotonic() - self._partner_first_sound_at, self._overlap_chunks)
                self._partner_first_sound_at = None
            self._drop_rest_of_turn = False
            await super()._handle_msg_turn_complete(message)
            pending = self.__dict__.pop("_pending_notes", None)
            for note in pending or ():
                await self._push_note(note)

    return TranscriptHintedLiveService


async def run_bot(webrtc_connection, config: CallConfig) -> None:
    if config.engine not in GEMINI_ENGINES:
        from server import engines

        return await engines.run_engine(webrtc_connection, config)
    from pipecat.frames.frames import EndFrame, LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
    from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
    from pipecat.services.google.gemini_live.llm import ProactivityConfig
    from pipecat.services.llm_service import FunctionCallParams
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.workers.runner import WorkerRunner

    model, vad, user_params, vad_meta = live_config_for(config.mode, engine=config.engine)
    record = CallRecord()
    if vad_meta:
        logger.info("Chat VAD knobs applied (%s): %s", config.mode, vad_meta)
    logger.info("Live model for %s: %s", config.mode, model)
    if not getattr(vad, "disabled", False):
        logger.info(
            "Gemini VAD applied (%s): start=%s prefix_ms=%s end=%s silence_ms=%s",
            config.mode,
            vad.start_sensitivity.name.removeprefix("START_SENSITIVITY_"),
            vad.prefix_padding_ms,
            vad.end_sensitivity.name.removeprefix("END_SENSITIVITY_"),
            vad.silence_duration_ms,
        )

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_in_sample_rate=MIC_SAMPLE_RATE,
            audio_in_filter=build_audio_in_filter(),
            audio_out_enabled=True,
            audio_out_10ms_chunks=2,
        ),
    )

    tools = live_tools(config)
    listener = make_turn_listener(config, record)
    instruction = config.system_instruction
    if listener is not None and listener.instruction_suffix.strip():
        instruction = f"{instruction}\n\n{listener.instruction_suffix.strip()}"

    proactive_audio = proactive_audio_from_env()
    logger.info("Proactive audio: %s", "on" if proactive_audio else "off")
    live_service = live_service_class()
    llm = live_service(
        project_id=get_project_id(),
        location=os.getenv("LOCATION", "us-central1"),
        tools=tools,
        inference_on_context_initialization=config.opener,
        settings=live_service.Settings(
            model=model,
            voice=config.voice,
            system_instruction=instruction,
            temperature=1.0,
            language="en-US",
            vad=vad,
            context_window_compression={"enabled": True},
            enable_affective_dialog=affective_dialog_from_env(engine=config.engine),
            **({"proactivity": ProactivityConfig(proactive_audio=True)} if proactive_audio else {}),
        ),
    )

    if listener is not None:
        listener.attach(llm)

    context = LLMContext()
    pair_kwargs = {"realtime_service_mode": True}
    if user_params is not None:
        pair_kwargs["user_params"] = user_params
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context, **pair_kwargs)
    audiobuffer = AudioBufferProcessor(sample_rate=MIC_SAMPLE_RATE, num_channels=1)

    pipeline = Pipeline([
        transport.input(),
        user_aggregator,
        llm,
        make_usage_collector(record.usage),
        transport.output(),
        audiobuffer,
        assistant_aggregator,
    ])
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True, enable_usage_metrics=True))
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    async def complete_mission(params: FunctionCallParams):
        if not record.learner_has_spoken():
            logger.info("complete_mission ignored: the learner has not spoken yet")
            await params.result_callback(NOT_YET_RESULT)
            return
        record.completed = True
        await worker.queue_frames([RTVIServerMessageFrame(data={"type": "mission_complete", "args": params.arguments})])
        await params.result_callback({"status": "recorded"})

    async def recall_past_conversations(params: FunctionCallParams):
        query = str((params.arguments or {}).get("query") or "")
        result = await asyncio.to_thread(call_tools.recall, query, config.partner)
        logger.info("recall_past_conversations(%r): %s, %d snippet(s)", query, result["status"], len(result.get("snippets", [])))
        await params.result_callback(result)

    shared_videos: "set[str]" = set()
    last_clip_at: List[float] = []

    async def share_clip(params: FunctionCallParams):
        query = str((params.arguments or {}).get("phrase_or_topic") or "")
        hold = call_tools.share_clip_hold(record.chunks, last_clip_at[-1] if last_clip_at else None, time.monotonic())
        if hold:
            logger.info("share_clip(%r): held", query)
            await params.result_callback(hold)
            return
        clip = await asyncio.to_thread(call_tools.find_clip, query, shared_videos)
        logger.info("share_clip(%r): %s", query, clip and clip["video_id"])
        if clip:
            shared_videos.add(clip["video_id"])
            last_clip_at.append(time.monotonic())
            record.add_note("Partner (shared clip)", call_tools.clip_record_text(clip))
            await worker.queue_frames([RTVIServerMessageFrame(data={"type": "shared_clip", "clip": clip})])
        await params.result_callback(call_tools.share_clip_result(clip))

    if tools is not None:
        llm.register_function(call_tools.RECALL_TOOL, recall_past_conversations)
        llm.register_function(call_tools.SHARE_CLIP_TOOL, share_clip)
        if mission_tools(config) is not None:
            llm.register_function("complete_mission", complete_mission)

    @user_aggregator.event_handler("on_user_turn_message_added")
    async def on_user_message(aggregator, message):
        if message.content not in (OPENER_TEXT, opener_text(config.partner)):
            turns_before = len(record.chunks)
            record.add_user(message.content)
            if listener is not None and len(record.chunks) > turns_before:
                await notify_turn_listener(listener, record.chunks[-1][1])

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn(aggregator, message):
        record.add_partner(message.content)

    @audiobuffer.event_handler("on_track_audio_data")
    async def on_track_audio(buffer, user_audio, bot_audio, sample_rate, num_channels):
        record.add_mic(user_audio)

    clock = CallClock()
    llm.call_mode = config.mode
    llm.pause_check = lambda: clock.paused
    llm.on_reengage = lambda count, silent: record.add_note("system", f"silence re-engage #{count} at {clock.elapsed():.1f}s")
    pause_limit = pause_limit_from_env()
    clock_changed = asyncio.Event()

    async def end_at_time_limit():
        # 일시정지·재개마다 남은 시간을 다시 계산한다(타이머를 한 번만 걸면 멈춘 동안도 줄어든다).
        while True:
            clock_changed.clear()  # check 전에 비워야 그 사이에 온 변화를 놓치지 않는다
            reason, wait = clock.check(config.time_limit, pause_limit)
            if reason:
                break
            try:
                await asyncio.wait_for(clock_changed.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
        logger.info("Session ended: %s (limit %s, pause limit %ss)", reason, config.time_limit or "none", pause_limit)
        data = {"type": "time_limit"} if reason == "time_limit" else {"type": "time_limit", "reason": reason}
        await worker.queue_frames([RTVIServerMessageFrame(data=data), EndFrame()])

    # 제한 시간이 없는 친구 통화에서 Gemini 연결이 끝내 살아나지 않으면 통화를 끝내 화면이 '다시 걸까요?'를 보이게 한다.
    # (pipecat은 그냥 두면 말 없는 통화로 계속 열려 있다.)
    gave_up = False

    @worker.event_handler("on_pipeline_error")
    async def on_pipeline_error(worker_, frame):
        nonlocal gave_up
        if gave_up or not llm_gave_up(getattr(frame, "error", "")):
            return
        gave_up = True
        logger.warning("Gemini connection lost for good; ending the call")
        await worker.queue_frames([EndFrame()])

    async def handle_share(rtvi, data: dict) -> None:
        """학습자가 통화 중 보낸 글·링크를 읽어 파트너에게 학습자 글로 넣고, 전문에 남기고, 화면에 결과를 알린다."""
        text = call_tools.clean_share_text(data.get("text"))
        ack = {"type": "share_ack", "id": data.get("id"), "ok": bool(text)}
        if text:
            urls = call_tools.extract_urls(text)
            ctx = None
            if urls:
                try:
                    ctx = await asyncio.wait_for(asyncio.to_thread(call_tools.link_context, urls[0]), timeout=SHARE_FETCH_TIMEOUT_SEC)
                except asyncio.TimeoutError:
                    ctx = call_tools.LinkContext(urls[0], error="timeout")
                ack.update(url=ctx.url, title=ctx.title, opened=ctx.ok)
            logger.info("Share from learner: %s", ctx and (ctx.url, ctx.kind, ctx.title, ctx.error) or "text")
            record.add_note("Me (shared)", call_tools.share_record_text(text, ctx))
            await llm.send_learner_text(call_tools.share_prompt(text, ctx))
        await rtvi.send_server_message(ack)

    share_tasks: "set[asyncio.Task]" = set()

    # 클라이언트가 sendClientMessage("pause"|"resume"|"share")을 보내면 RTVIProcessor가 on_client_message를 부른다.
    @worker.rtvi.event_handler("on_client_message")
    async def on_client_message(rtvi, message):
        if message.type == "share" and config.mode != "teachback":
            task = asyncio.create_task(handle_share(rtvi, message.data if isinstance(message.data, dict) else {}))
            share_tasks.add(task)
            task.add_done_callback(share_tasks.discard)
        elif message.type == "telemetry":
            line = format_telemetry(message.data)
            if line:
                logger.info("Telemetry [%s %s] %s", config.partner or "park", config.mode, line)
        elif message.type == "pause":
            if clock.pause():
                clock_changed.set()
                await rtvi.interrupt_bot()  # 말하던 튜터를 멈춘다
            await rtvi.send_server_message({"type": "paused"})
        elif message.type == "resume":
            if clock.resume():
                clock_changed.set()
            await rtvi.send_server_message({"type": "resumed"})

    limiter: Optional[asyncio.Task] = None
    recording = False

    async def stop_recording():
        nonlocal recording
        if recording:
            recording = False
            await audiobuffer.stop_recording()

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        nonlocal limiter, recording
        record.started_at = time.time()
        clock.start()
        await audiobuffer.start_recording()
        recording = True
        limiter = asyncio.create_task(end_at_time_limit())
        if config.opener:
            context.add_message({"role": "user", "content": opener_text(config.partner)})
            await worker.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        await stop_recording()
        await runner.cancel()

    try:
        await runner.run()
    finally:
        if limiter:
            limiter.cancel()
        for task in share_tasks:
            task.cancel()
        await stop_recording()
        record.paused_sec = clock.paused_total()
        meta_line = " ".join(part for part in (vad_meta, call_knobs_summary(config.mode)) if part) or None
        saved = await asyncio.to_thread(finish_call, record, config, model, None, meta_line)
        logger.info("Call finished; transcript saved: %s", saved)
        schedule_partner_memory_update(saved, config, record)
        notify_call_saved(saved, config, record)

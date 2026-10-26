"""cascade_flux 엔진: Deepgram Flux(종료 감지 내장) -> Vertex 텍스트 LLM -> Cartesia sonic-3.6 (설계 1.1 C, 후보 C5).

shell(engines/shell.py)이 전송·집계기·녹음·시계·마무리를 맡고, 이 모듈은 서비스 묶음(EngineParts)만 만든다.
- 끼어들기: 시작 전략을 MinWordsUserTurnStartStrategy(min_words=3)로 바꿔, 파트너가 말하는 동안 학습자의 "mm-hm"·"yeah"가
  파트너를 멈추지 못하게 한다. 끝 전략은 Flux가 권하는 EagerUserTurnStopStrategy(예측 종료에 미리 답을 만든다).
- 파트너가 말하는 글에는 지문(*웃음*, (laughs), [laughter])과 마크다운이 없어야 한다(TTS가 전부 읽는다). TTS 앞의 글 필터가 지운다.
- 도구·공유·알림은 shell이 건너뛴다(docs/engines.md). 키가 없으면 unavailable_reason이 문장을 돌려주고 seam(call_bot.parse_call_config)이 400으로 바꾼다.
"""

import logging
import os
import re
import time
from typing import Optional

from server.config_utils import get_project_id
from server.engines.base import EngineParts

logger = logging.getLogger(__name__)

DEEPGRAM_KEY_ENV = "DEEPGRAM_API_KEY"
CARTESIA_KEY_ENV = "CARTESIA_API_KEY"
LLM_MODEL_ENV = "CASCADE_LLM_MODEL"
DEFAULT_LLM_MODEL = "gemini-2.5-flash"
STT_MODEL = "flux-general-en"
TTS_MODEL = "sonic-3.6"
# 파트너가 말하는 중에 이 낱말 수 이상이 들려야 끼어들기로 친다. 한두 낱말 맞장구는 파트너를 멈추지 못한다.
BARGE_IN_MIN_WORDS = 3

# Cartesia 문서가 음성 에이전트용으로 권하는 안정적인 미국 영어 목소리(docs.cartesia.ai Sonic 3.6 "Voice selection").
VOICE_DANIEL = "47c38ca4-5f35-497b-b1a3-415245fb35e1"  # Daniel, en-US 남성
VOICE_SKYLAR = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"  # Skylar, en-US 여성
VOICE_JACQUELINE = "9626c31c-bec5-4cca-baa8-f8ba9e84c8bc"  # Jacqueline, en-US 여성
PARTNER_VOICES = {"jake": VOICE_DANIEL, "brian": VOICE_DANIEL, "priya": VOICE_SKYLAR}
DEFAULT_VOICE_ID = VOICE_JACQUELINE


def voice_for_partner(partner: Optional[str]) -> str:
    return PARTNER_VOICES.get((partner or "").lower(), DEFAULT_VOICE_ID)


def llm_model_from_env() -> str:
    return os.getenv(LLM_MODEL_ENV, "").strip() or DEFAULT_LLM_MODEL


def _key(name: str) -> str:
    return os.getenv(name, "").strip()


def unavailable_reason() -> Optional[str]:
    """키가 없으면 400으로 돌려줄 문장. 값은 어디에도 적지 않고 이름만 쓴다."""
    missing = [name for name in (DEEPGRAM_KEY_ENV, CARTESIA_KEY_ENV) if not _key(name)]
    if missing:
        return f"cascade_flux 엔진에 필요한 키가 서버에 없습니다: {', '.join(missing)}"
    return None


STAGE_DIRECTION = re.compile(r"\*[^*\n]*\*|\([^)\n]*\)|\[[^\]\n]*\]|<[^>\n]*>")
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")
MARKUP_CHARS = re.compile(r"[*#`~]|(?<![\w])_+|_+(?![\w])")
LIST_BULLET = re.compile(r"(?m)^[ \t]*(?:[-+]|\d+\.|#+)[ \t]+")
EXTRA_SPACE = re.compile(r"[ \t]{2,}")


def spoken_text(text: str) -> str:
    """TTS에 보낼 글에서 지문·마크다운·이모지를 지운다. 앞뒤 공백은 그대로 둔다(스트리밍 조각이 이어 붙는다)."""
    cleaned = STAGE_DIRECTION.sub("", text)
    cleaned = LIST_BULLET.sub("", cleaned)
    cleaned = EMOJI.sub("", cleaned)
    cleaned = MARKUP_CHARS.sub("", cleaned)
    return EXTRA_SPACE.sub(" ", cleaned)


def make_spoken_text_filter():
    from pipecat.utils.text.base_text_filter import BaseTextFilter

    class SpokenTextFilter(BaseTextFilter):
        async def filter(self, text: str) -> str:
            return spoken_text(text)

    return SpokenTextFilter()



class TurnTimer:
    """Flux가 학습자 차례의 끝(on_end_of_turn)을 알린 때부터 첫 TTS 소리가 나올 때까지를 한 차례마다 한 줄로 남긴다."""

    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._end_of_turn_at: Optional[float] = None
        self.turn = 0

    def end_of_turn(self) -> None:
        self._end_of_turn_at = self._clock()

    def first_audio(self) -> Optional[float]:
        if self._end_of_turn_at is None:
            return None
        ms = (self._clock() - self._end_of_turn_at) * 1000
        self._end_of_turn_at = None
        self.turn += 1
        logger.info("Turn latency #%d: %.0f ms (learner end of turn -> first TTS audio)", self.turn, ms)
        return ms


def make_tts_class():
    from pipecat.frames.frames import TTSAudioRawFrame
    from pipecat.services.cartesia.tts import CartesiaTTSService

    class TimedCartesiaTTSService(CartesiaTTSService):
        """CartesiaTTSService와 같고, 차례마다 첫 소리가 나가는 순간만 TurnTimer에 알린다."""

        turn_timer: Optional[TurnTimer] = None

        async def push_frame(self, frame, *args, **kwargs):
            if self.turn_timer is not None and isinstance(frame, TTSAudioRawFrame):
                self.turn_timer.first_audio()
            await super().push_frame(frame, *args, **kwargs)

    return TimedCartesiaTTSService



def build_user_params():
    from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
    from pipecat.turns.user_start.min_words_user_turn_start_strategy import MinWordsUserTurnStartStrategy
    from pipecat.turns.user_stop import EagerUserTurnStopStrategy
    from pipecat.turns.user_turn_strategies import UserTurnStrategies

    return LLMUserAggregatorParams(
        user_turn_strategies=UserTurnStrategies(
            start=[MinWordsUserTurnStartStrategy(min_words=BARGE_IN_MIN_WORDS)],
            stop=[EagerUserTurnStopStrategy()],
        )
    )


def build_parts(config) -> EngineParts:
    reason = unavailable_reason()
    if reason:
        raise RuntimeError(reason)

    from pipecat.services.deepgram.flux.stt import DeepgramFluxSTTService
    from pipecat.services.google.vertex.llm import GoogleVertexLLMService
    from pipecat.transcriptions.language import Language

    llm_model = llm_model_from_env()
    timer = TurnTimer()

    stt = DeepgramFluxSTTService(
        api_key=_key(DEEPGRAM_KEY_ENV),
        enable_eager_end_of_turn=True,
        settings=DeepgramFluxSTTService.Settings(model=STT_MODEL),
    )

    @stt.event_handler("on_end_of_turn")
    async def on_end_of_turn(service, transcript):
        timer.end_of_turn()

    llm = GoogleVertexLLMService(
        project_id=get_project_id(),
        location=os.getenv("LOCATION", "us-central1"),
        settings=GoogleVertexLLMService.Settings(model=llm_model, system_instruction=config.system_instruction),
    )

    tts_class = make_tts_class()
    tts = tts_class(
        api_key=_key(CARTESIA_KEY_ENV),
        settings=tts_class.Settings(model=TTS_MODEL, voice=voice_for_partner(config.partner), language=Language.EN),
        text_filters=[make_spoken_text_filter()],
    )
    tts.turn_timer = timer

    return EngineParts(
        model_name=f"flux+{llm_model}+{TTS_MODEL}",
        llm=llm,
        stt=stt,
        tts=tts,
        user_params=build_user_params(),
        realtime_service_mode=False,
    )

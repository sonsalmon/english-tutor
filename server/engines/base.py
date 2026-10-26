"""통화 엔진 스위치의 계약(docs/engines.md). pipecat을 불러오지 않는 가벼운 모듈이다.

call_bot.parse_call_config가 이 모듈로 request_data.engine을 검사하고, 실험 엔진 모듈(openai_live·cascade_flux)은
`build_parts(config) -> EngineParts`로 자기 서비스 묶음을 shell에 건넨다.
"""

import importlib
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable

DEFAULT_ENGINE = "gemini_live"
# call_bot.run_bot의 기본 경로가 처리하는 엔진. 나머지는 engines.run_engine으로 간다.
GEMINI_ENGINES = ("gemini_live", "gemini_live_notes")
ALLOWED_ENGINES = ("gemini_live", "gemini_live_notes", "openai_live", "cascade_flux")
# 실험 엔진 이름 -> 모듈 경로(지연 import). 모듈이 아직 없으면 요청을 400으로 막는다.
ENGINE_MODULES = {
    "openai_live": "server.engines.openai_live",
    "cascade_flux": "server.engines.cascade_flux",
}
ENGINE_NOT_READY = "이 엔진은 아직 준비되지 않았습니다."


@runtime_checkable
class NoteSink(Protocol):
    """감독 메모를 받는 쪽(엔진의 LLM 서비스). 말하지 않고 다음 차례에 참고할 내용으로만 넣는다."""

    async def send_note(self, text: str) -> None: ...


@runtime_checkable
class TurnListener(Protocol):
    """학습자 차례가 끝날 때마다 불리는 곁가지(조언자). call_bot.configure_turn_listener로 등록한다."""

    instruction_suffix: str

    def attach(self, note_sink: NoteSink) -> None: ...

    async def on_user_turn(self, text: str) -> None: ...


@dataclass
class EngineParts:
    """엔진 모듈이 shell에 건네는 서비스 묶음. shell이 전송·집계기·녹음·시계·마무리를 맡는다.

    파이프라인: transport.input -> [stt] -> user_aggregator -> llm -> usage -> [tts] -> transport.output -> audiobuffer -> assistant_aggregator
    model_name은 전문 메타 `model`에 적힌다(pricing이 모르는 이름이면 cost_usd는 None).
    """

    model_name: str
    llm: Any
    stt: Optional[Any] = None
    tts: Optional[Any] = None
    user_params: Optional[Any] = None  # LLMUserAggregatorParams
    realtime_service_mode: bool = True  # 음성-음성 모델이면 True, STT->LLM->TTS 캐스케이드면 False
    audio_out_sample_rate: Optional[int] = None


def engine_unavailable_reason(name: str) -> Optional[str]:
    """이 엔진을 지금 쓸 수 없는 이유(한국어 문장). 쓸 수 있으면 None.

    Gemini 엔진은 늘 가능하다. 실험 엔진은 모듈이 있어야 하고, 모듈이 `unavailable_reason() -> Optional[str]`를
    가지면(예: API 키 없음) 그 이유를 따른다."""
    if name in GEMINI_ENGINES:
        return None
    path = ENGINE_MODULES.get(name)
    if path is None:
        return ENGINE_NOT_READY
    try:
        module = importlib.import_module(path)
    except ModuleNotFoundError as e:
        if e.name == path:
            return ENGINE_NOT_READY
        return f"엔진 모듈을 불러오지 못했습니다: {e}"
    except Exception as e:  # noqa: BLE001 - 엔진 모듈의 import 실패가 /api/offer를 500으로 만들지 않게
        return f"엔진 모듈을 불러오지 못했습니다: {e}"
    check = getattr(module, "unavailable_reason", None)
    return check() if callable(check) else None

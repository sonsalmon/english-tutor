"""통화 비용 추정: 모델별 토큰 단가와 사용량 합산.

단가는 100만 토큰당 미국 달러다. 출처: https://ai.google.dev/gemini-api/docs/pricing
(2026-10-20 확인). 표에 없는 모델이면 비용을 None으로 돌려준다(틀린 숫자를 만들지 않는다).
캐시된 입력 토큰은 따로 깎지 않는다(조금 높게 잡는 방향의 추정).
표준 라이브러리만 쓴다.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

PRICING_SOURCE_URL = "https://ai.google.dev/gemini-api/docs/pricing"
PRICING_DATE = "2026-10-20"

LIVE_MODEL = "gemini-live-2.5-flash-native-audio"
TUTOR_MODEL = "gemini-2.5-flash"

# USD / 1M tokens
PRICES: Dict[str, Dict[str, float]] = {
    LIVE_MODEL: {"input_text": 0.50, "input_audio": 3.00, "output_text": 2.00, "output_audio": 12.00},
    # 텍스트 분석 모델은 출력 단가가 하나다(오디오 출력은 쓰지 않는다).
    TUTOR_MODEL: {"input_text": 0.30, "input_audio": 1.00, "output_text": 2.50, "output_audio": 2.50},
}

_KEYS = ("input_text", "input_audio", "output_text", "output_audio")


@dataclass
class UsageTotals:
    """통화(또는 분석) 하나의 토큰 합계. 4개 구간으로 나눠 센다."""

    input_text: int = 0
    input_audio: int = 0
    output_text: int = 0
    output_audio: int = 0

    def is_empty(self) -> bool:
        return not any(getattr(self, k) for k in _KEYS)

    def add_tokens(self, prompt: int, completion: int, input_audio: Optional[int], output_audio: Optional[int]) -> None:
        """prompt·completion은 오디오를 포함한 전체 토큰 수다. 오디오를 빼고 남은 만큼을 텍스트로 센다."""
        in_audio = max(0, min(input_audio or 0, prompt))
        out_audio = max(0, min(output_audio or 0, completion))
        self.input_audio += in_audio
        self.input_text += max(0, prompt) - in_audio
        self.output_audio += out_audio
        self.output_text += max(0, completion) - out_audio

    def add_metadata(self, usage: Any) -> None:
        """google-genai의 usage_metadata(Vertex generate_content 응답)를 더한다. None이면 무시."""
        if usage is None:
            return
        prompt = (getattr(usage, "prompt_token_count", 0) or 0) + (getattr(usage, "tool_use_prompt_token_count", 0) or 0)
        # 생각(thinking) 토큰도 출력 단가로 청구된다.
        completion = (getattr(usage, "candidates_token_count", 0) or 0) + (getattr(usage, "thoughts_token_count", 0) or 0)
        self.add_tokens(
            prompt,
            completion,
            modality_tokens(getattr(usage, "prompt_tokens_details", None), "AUDIO"),
            modality_tokens(getattr(usage, "candidates_tokens_details", None), "AUDIO"),
        )

    def cost(self, model: str) -> Optional[float]:
        """USD 비용(소수 6자리까지 반올림). 단가표에 없는 모델이면 None."""
        return estimate_cost(model, self)


def modality_tokens(details: Any, name: str) -> int:
    """[ModalityTokenCount(modality, token_count)] 에서 한 구간(AUDIO 등)의 토큰 수."""
    total = 0
    for item in details or []:
        modality = getattr(item, "modality", None)
        label = str(getattr(modality, "name", None) or getattr(modality, "value", None) or modality or "").upper()
        if label == name:
            total += getattr(item, "token_count", 0) or 0
    return total


def estimate_cost(model: str, usage: UsageTotals) -> Optional[float]:
    prices = PRICES.get(model)
    if prices is None:
        return None
    total = sum(getattr(usage, k) * prices[k] for k in _KEYS) / 1_000_000
    return round(total, 6)


def combine_cost(live: Optional[float], tutoring: Optional[float]) -> Dict[str, Optional[float]]:
    """화면용 비용 묶음. 한쪽만 알면 total은 아는 쪽 합계이고, 둘 다 모르면 None."""
    known = [v for v in (live, tutoring) if v is not None]
    return {
        "live": live,
        "tutoring": tutoring,
        "total": round(sum(known), 6) if known else None,
    }

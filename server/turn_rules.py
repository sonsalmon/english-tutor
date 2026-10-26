"""말차례 규칙 접미 (묶음 4, P2·P5).

친구 통화(smalltalk·freetalk)의 지시문 끝에 영어 규칙 블록을 붙인다. 두 엔진(Gemini 2.5·3.8)에 같은 글이 간다.
- hesitation (P2): 학습자가 말을 흐리거나 문장 중간에서 쉬면 짧은 기다림 신호 하나(5낱말 이하)만 말하고, 대신 끝내지 않는다.
- backchannel (P5): 학습자가 "yeah" 같은 짧은 반응만 하면 질문 대신 자기 이야기를 한두 문장 잇는다.

LIVE_TURN_RULES=hesitation,backchannel (쉼표 목록). 설정하지 않으면 둘 다 켠다. `off`이거나 빈 값이면 접미를 붙이지 않는다.
`/api/offer`에서 `resume.with_resume` 바로 뒤에 호출한다(이어 가기 블록과 같은 방식).
"""

import os
from dataclasses import replace
from typing import Mapping, Optional, Tuple

from server.call_bot import CHAT_MODES, CallConfig

TURN_RULES_ENV = "LIVE_TURN_RULES"
DEFAULT_RULES = ("hesitation", "backchannel")
SUFFIX_MAX_WORDS = 120

HESITATION = (
    "If the learner trails off ('um...', 'because, uh,') or pauses in the middle of a sentence, wait for them. "
    "You may say at most ONE short waiting signal of five words or fewer ('Take your time.', 'Mm-hm.', \"I'm listening.\") per pause. "
    "Never finish their sentence, never guess what they mean, never change the topic, and never ask a question until they have finished."
)
BACKCHANNEL = (
    "If the learner only gives a short reaction ('yeah', 'mm-hm', 'right', 'oh'), read it as 'go on': "
    "tell one or two sentences of your own story, ending with a period. "
    "Not one question mark in that turn: no 'you know?', no 'right?', no 'X, though?'."
)
_TEXTS = {"hesitation": HESITATION, "backchannel": BACKCHANNEL}
HEADER = "TURN-TAKING RULES (these apply to every turn of this call):"


def parse_rules(env: Optional[Mapping[str, str]] = None) -> Tuple[str, ...]:
    """LIVE_TURN_RULES에서 켜진 규칙 이름들(고정 순서). 설정이 없으면 기본 둘 다, off·빈 값이면 없음. 모르는 이름은 무시한다."""
    env = os.environ if env is None else env
    raw = env.get(TURN_RULES_ENV)
    if raw is None:
        return DEFAULT_RULES
    wanted = {part.strip().lower() for part in raw.split(",")}
    return tuple(name for name in DEFAULT_RULES if name in wanted)


def suffix(rules: Tuple[str, ...]) -> str:
    if not rules:
        return ""
    return "\n\n" + HEADER + "\n" + "\n".join(f"- {_TEXTS[name]}" for name in rules)


def with_turn_rules(config: CallConfig, env: Optional[Mapping[str, str]] = None) -> CallConfig:
    """친구 통화 모드(smalltalk·freetalk)에서 켜진 규칙의 접미를 붙인 설정을, 아니면 같은 설정을 돌려준다."""
    if config.mode not in CHAT_MODES:
        return config
    text = suffix(parse_rules(env))
    if not text:
        return config
    return replace(config, system_instruction=config.system_instruction + text)

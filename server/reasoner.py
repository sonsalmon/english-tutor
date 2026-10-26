"""조용한 조언자(reasoner): 친구 수다 통화에서 라이브 화자 옆에 붙어 감독 메모 한 줄을 건넨다.

설계: .omo/dag/night-3/design.md 1.2~1.5, 2(P6), 3(C2).
engine=gemini_live_notes 일 때만 `listener_factory`가 TurnListener를 돌려준다(다른 엔진은 None이라 통화는 그대로 돈다).
학습자 차례가 끝날 때마다 Vertex 텍스트 모델(env REASONER_MODEL, 없으면 TUTOR_MODEL)에 최근 대화를 보내
영어 한 줄(40낱말 이하) 메모를 받아 `note_sink.send_note`로 라이브 세션에 넣는다. 말하는 경로와 따로 돌아 지연이 늘지 않는다.
"""

import asyncio
import json
import logging
import os
import re
import time
from typing import Any, Callable, List, Optional, Tuple

from server.engines.base import NoteSink

logger = logging.getLogger(__name__)

NOTES_ENGINE = "gemini_live_notes"
REASONER_MODEL_ENV = "REASONER_MODEL"
MAX_NOTE_WORDS = 40
RECENT_TURNS = 8
MIN_LEARNER_WORDS = 3
# 조언자 프롬프트에 넣는 지시문 발췌 길이 상한(글자 수)
MAX_STANCE_CHARS = 1200
MAX_MEMORY_CHARS = 1500

NOTE_PREFIX = "[Director's note, silent, never read aloud or mention] "

# design.md 2절 P6. 클라이언트 지시문이 아니라 서버가 이 엔진에서만 붙인다.
INSTRUCTION_SUFFIX = (
    "DIRECTOR'S NOTES: during the call you may receive a message starting with \"[Director's note\". "
    "Follow it silently. Never read it, quote it, or mention notes. "
    "Do not reply to it; wait for the learner."
)

PROMPT = """You are the quiet director behind a phone call between a language learner and their friend {name}.
{name} is an AI friend with a real personality. You never talk to the learner. You give {name} ONE short private note
for the next turn, so {name} sounds like a person with their own opinions and stories, not an agreeable assistant.

{name}'s personality and opinions:
{stance}
{memory}
Recent conversation (Me = the learner, Partner = {name}):
{turns}

Write ONE note in English, at most {max_words} words, addressed to {name}. Pick what helps most right now:
- what to push back on (one playful reason, then let it go if the learner stays firm);
- which of {name}'s own opinions or stories to bring in (continue a story beat, do not start a lecture);
- whether to answer the learner's question first before asking anything back.
Never correct the learner's English. Never invent facts about the learner. Do not mention notes or a director.

Return only JSON: {{"note": "<the note>", "hold_for_end": []}}
If nothing is worth saying, return {{"note": "", "hold_for_end": []}}."""


def word_count(text: str) -> int:
    return len(text.split())


def clamp_note(note: str, max_words: int = MAX_NOTE_WORDS) -> Optional[str]:
    """메모를 한 줄로 정리하고 낱말 수를 지킨다. 넘치면 문장 경계에서 자르고, 자를 곳이 없으면 버린다(None)."""
    text = re.sub(r"\s+", " ", note or "").strip().strip('"').strip()
    if not text:
        return None
    if word_count(text) <= max_words:
        return text
    cut = " ".join(text.split()[:max_words])
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if cut[-1] in ".!?":
        end = len(cut) - 1
    if end <= 0:
        return None
    return cut[: end + 1]


def parse_note(raw: Any) -> Tuple[str, List[str]]:
    """모델 응답에서 (메모, 보류 항목)을 꺼낸다. JSON이 아니면 글 전체를 메모로 본다."""
    text = raw if isinstance(raw, str) else ""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        data = json.loads(text)
    except ValueError:
        return text, []
    if isinstance(data, dict):
        note = data.get("note")
        hold = data.get("hold_for_end")
        return (note if isinstance(note, str) else ""), [h for h in (hold or []) if isinstance(h, str)] if isinstance(hold, list) else []
    return "", []


def persona_name(instruction: str) -> str:
    match = re.search(r"You are ((?:Ms\. |Mr\. )?[A-Z][a-z]+)", instruction or "")
    return match.group(1) if match else "the friend"


def persona_stance(instruction: str) -> str:
    """지시문의 STANCE(없으면 VALUES & OPINIONS) 문단을 그대로 뽑는다."""
    lines = (instruction or "").splitlines()
    for header in ("STANCE", "VALUES & OPINIONS"):
        for i, line in enumerate(lines):
            if line.strip() == header or line.startswith(header + ":"):
                block: List[str] = []
                for follow in lines[i + 1 :]:
                    if not follow.strip():
                        break
                    block.append(follow.strip())
                if block:
                    return "\n".join(block)[:MAX_STANCE_CHARS]
    stance_lines = [ln.strip() for ln in lines if ln.strip().startswith("STANCE")]
    return "\n".join(stance_lines)[:MAX_STANCE_CHARS]


def memory_brief(instruction: str) -> str:
    """지시문에 이미 들어 있는 기억 brief(<<< >>> 사이)."""
    match = re.search(r"<<<\n(.*?)\n>>>", instruction or "", re.S)
    return match.group(1).strip()[:MAX_MEMORY_CHARS] if match else ""


def build_prompt(instruction: str, chunks: List[Tuple[str, str]]) -> str:
    name = persona_name(instruction)
    stance = persona_stance(instruction) or "(no stated opinions)"
    brief = memory_brief(instruction)
    memory = f"\nWhat {name} remembers about the learner (private, never quote it):\n{brief}\n" if brief else ""
    turns = [(s, t) for s, t in chunks if s in ("Me", "Partner")][-RECENT_TURNS:]
    return PROMPT.format(
        name=name,
        stance=stance,
        memory=memory,
        turns="\n".join(f"{s}: {t}" for s, t in turns),
        max_words=MAX_NOTE_WORDS,
    )


def default_generate_text() -> Callable[[str], Any]:
    from server.tutor import make_generate_text

    return make_generate_text(os.getenv(REASONER_MODEL_ENV) or None)


class Reasoner:
    """TurnListener 구현. 동시에 한 요청만 돌고, 다음 학습자 차례보다 늦게 온 결과는 버린다."""

    instruction_suffix = INSTRUCTION_SUFFIX

    def __init__(
        self,
        config: Any,
        record: Any,
        generate_text: Optional[Callable[[str], Any]] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._instruction = config.system_instruction
        self._record = record
        self._generate_text = generate_text
        self._clock = clock
        self._sink: Optional[NoteSink] = None
        self._seq = 0  # 학습자 차례 번호(말을 건너뛴 차례도 센다)
        self._pending: Optional[Tuple[int, float]] = None  # 아직 처리하지 않은 가장 최근 차례
        self._worker: Optional["asyncio.Task[None]"] = None

    def attach(self, note_sink: NoteSink) -> None:
        self._sink = note_sink

    async def on_user_turn(self, text: str) -> None:
        self._seq += 1
        if word_count(text or "") < MIN_LEARNER_WORDS:
            self._pending = None  # 짧은 맞장구는 부르지 않고, 앞서 돌던 결과는 오래된 것이 된다
            return
        self._pending = (self._seq, self._clock())
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while self._pending is not None:
            seq, started = self._pending
            self._pending = None
            try:
                await self._one_turn(seq, started)
            except Exception as e:  # noqa: BLE001 - 조언자 오류가 통화를 막지 않는다
                logger.error("Reasoner failed: %s", e)

    async def _one_turn(self, seq: int, started: float) -> None:
        if self._sink is None:
            return
        if self._generate_text is None:
            self._generate_text = await asyncio.to_thread(default_generate_text)
        prompt = build_prompt(self._instruction, list(self._record.chunks))
        raw = await asyncio.to_thread(self._generate_text, prompt)
        if seq != self._seq:
            logger.info("Note dropped (a newer learner turn arrived)")
            return
        note, hold = parse_note(raw)
        if hold:
            logger.info("Reasoner hold for the end: %r", hold)
        clamped = clamp_note(note)
        if clamped is None:
            if note.strip():
                logger.info("Note dropped (over %d words): %r", MAX_NOTE_WORDS, note)
            return
        await self._sink.send_note(NOTE_PREFIX + clamped)
        logger.info("Note injected (%.1fs after learner turn): %r", self._clock() - started, clamped)


def listener_factory(config: Any, record: Any) -> Optional[Reasoner]:
    """call_bot.configure_turn_listener에 등록하는 factory. gemini_live_notes 통화에만 조언자를 붙인다."""
    if getattr(config, "engine", None) != NOTES_ENGINE:
        return None
    return Reasoner(config, record)

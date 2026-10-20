"""Pipecat 통화 파이프라인 (docs/spec.md 11절).

브라우저(PipecatClient + SmallWebRTC)가 /api/offer로 연결하면 이 모듈의 run_bot이
Gemini Live(Vertex) 통화를 돌린다. 통화가 끝나면 마이크 원음 WAV를 먼저, 그다음
전문(.md)을 저장한다. /api/tutor는 .md가 생기면 곧바로 분석을 시작하므로 순서가
반대면 WAV를 못 찾는 경합이 생긴다.
"""

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from google.genai.types import EndSensitivity, StartSensitivity

from server.config_utils import get_project_id
from server.lesson import session_time_limit_from_env
from server import partner_memory
from server.partner_memory import PARTNER_IDS, PARTNER_NAMES
from server.pricing import UsageTotals, estimate_cost
from server.transcript_store import (
    get_transcript_dir,
    save_call_audio,
    save_transcript,
    transcript_stem,
)

logger = logging.getLogger(__name__)

MODES = ("mission", "freetalk", "teachback", "smalltalk")
SMALLTALK_TIME_LIMIT_ENV = "SMALLTALK_TIME_LIMIT"
DEFAULT_SMALLTALK_TIME_LIMIT = 300
PAUSE_LIMIT_ENV = "PAUSE_LIMIT_SEC"
DEFAULT_PAUSE_LIMIT_SEC = 600
MAX_INSTRUCTION_CHARS = 30_000
MIC_SAMPLE_RATE = 16_000
MIC_MAX_BYTES = MIC_SAMPLE_RATE * 2 * 60 * 30  # 16bit mono, 30분
DEFAULT_VOICE = "Puck"
OPENER_TEXT = "[The learner just joined the call. Start as Ms. Park.]"
TURN_MODE_ENV = "TURN_MODE"
MISSION_RE = re.compile(r'trying to:\s*"([^"]+)"')
MIN_LEARNER_WORDS = 3
# Gemini 입력 받아쓰기가 잡음을 `{}`로 내보낼 때가 있다(2026-10-20 브라우저 시험: "{} hi, I'm ...").
NOISE_MARK_RE = re.compile(r"\{\s*\}")
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


def smalltalk_time_limit_from_env(env=None) -> int:
    """가벼운 대화 통화의 제한 시간(초). `SMALLTALK_TIME_LIMIT`(기본 300)."""
    env = os.environ if env is None else env
    return int(env.get(SMALLTALK_TIME_LIMIT_ENV, str(DEFAULT_SMALLTALK_TIME_LIMIT)))


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

    def check(self, time_limit: float, pause_limit: float) -> Tuple[Optional[str], float]:
        """(끝낼 이유, 다음 확인까지 기다릴 초). 이유는 "time_limit"·"pause_limit"·None."""
        if self.paused:
            wait = pause_limit - self.paused_for()
            return ("pause_limit", 0.0) if wait <= 0 else (None, wait)
        wait = time_limit - self.elapsed()
        return ("time_limit", 0.0) if wait <= 0 else (None, wait)


@dataclass(frozen=True)
class CallConfig:
    system_instruction: str
    mode: str
    voice: str = DEFAULT_VOICE
    partner: Optional[str] = None

    @property
    def mission(self) -> Optional[str]:
        return mission_title(self.system_instruction)

    @property
    def opener(self) -> bool:
        # Teach-back은 학생 Maya가 지시문대로 시작하고, 학습자가 먼저 말한다.
        return self.mode != "teachback"

    @property
    def time_limit(self) -> int:
        if self.mode == "smalltalk":
            return smalltalk_time_limit_from_env()
        return session_time_limit_from_env("teachback" if self.mode == "teachback" else None)


PARTNER_MEMORY_MODES = ("smalltalk", "freetalk")


def opener_text(partner: Optional[str]) -> str:
    """통화 시작 때 모델에 보내는 첫 사용자 메시지. 친구 통화면 그 친구 이름으로 시작하게 한다."""
    name = PARTNER_NAMES.get(partner or "", "Ms. Park")
    return f"[The learner just joined the call. Start as {name}.]"


# 이미 친구 기억 갱신을 걸어 둔 통화 전문 파일명(통화당 한 번, 실패하면 다시 걸 수 있게 뺀다).
_PARTNER_UPDATED: "set[str]" = set()
_background_tasks: "set[asyncio.Task]" = set()


def update_partner_memory_sync(partner_id: str, turns: List[Tuple[str, str]]) -> bool:
    from server.tutor import make_generate_text

    return partner_memory.update(partner_id, turns, generate_text=make_generate_text())


def schedule_partner_memory_update(saved: Any, config: "CallConfig", record: "CallRecord") -> Optional[asyncio.Task]:
    """저장된 통화가 친구 통화이고 학습자 발화가 있으면 이 통화의 턴만으로 기억 갱신을 뒤에서 돌린다. 걸지 않으면 None."""
    if not config.partner or saved is None:
        return None
    turns = list(record.chunks)
    if not any(speaker == "Me" and text.strip() for speaker, text in turns):
        return None
    key = getattr(saved, "name", str(saved))
    if key in _PARTNER_UPDATED:
        return None
    _PARTNER_UPDATED.add(key)
    partner_id = config.partner

    async def _run():
        try:
            if await asyncio.to_thread(update_partner_memory_sync, partner_id, turns):
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
    partner = data.get("partner")
    # 기억은 수다·자유 대화만 쓴다: 미션 역할극 발화는 학습자의 실제 사실이 아니다.
    if partner not in PARTNER_IDS or mode not in PARTNER_MEMORY_MODES:
        partner = None
    return CallConfig(system_instruction=instruction, mode=mode, voice=voice, partner=partner)


@dataclass
class CallRecord:
    started_at: float = field(default_factory=time.time)
    chunks: List[Tuple[str, str]] = field(default_factory=list)
    mic_pcm: bytearray = field(default_factory=bytearray)
    completed: bool = False
    paused_sec: float = 0.0
    usage: UsageTotals = field(default_factory=UsageTotals)

    def add_user(self, text: str) -> None:
        clean = " ".join(NOISE_MARK_RE.sub(" ", text or "").split())
        if clean:
            self.chunks.append(("Me", clean))

    def add_partner(self, text: str) -> None:
        if text and text.strip():
            self.chunks.append(("Partner", text.strip()))

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


def finish_call(record: CallRecord, config: CallConfig, model: str, ended_at: Optional[float] = None):
    ended_at = ended_at or time.time()
    started_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(record.started_at))
    try:
        if record.mic_pcm:
            save_call_audio(bytes(record.mic_pcm), transcript_stem(started_str), sample_rate=MIC_SAMPLE_RATE)
    except Exception as e:  # noqa: BLE001 - 원음 저장 실패가 전문 저장을 막지 않는다
        logger.error("Call audio save failed: %s", e)
    try:
        return save_transcript(
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
            },
            get_transcript_dir(),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Transcript save failed: %s", e)
        return None


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


def turn_settings():
    """TURN_MODE에 따라 (Gemini VAD 설정, 로컬 VAD·Smart Turn 사용자 설정)을 돌려준다."""
    from pipecat.processors.aggregators.llm_response_universal import LLMUserAggregatorParams
    from pipecat.services.google.gemini_live.llm import GeminiVADParams

    if os.getenv(TURN_MODE_ENV, "gemini") == "smart":
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
    # 말 사이 멈춤이 잦은 학습자: 작은 목소리도 말 시작으로 잡고, 1.2초 조용해야 끝으로 본다(10-16 조정값).
    return GeminiVADParams(
        start_sensitivity=StartSensitivity.START_SENSITIVITY_HIGH,
        end_sensitivity=EndSensitivity.END_SENSITIVITY_LOW,
        prefix_padding_ms=300,
        silence_duration_ms=1200,
    ), None


async def run_bot(webrtc_connection, config: CallConfig) -> None:
    from pipecat.frames.frames import EndFrame, LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
    from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
    from pipecat.services.google.gemini_live.llm import ProactivityConfig
    from pipecat.services.google.gemini_live.vertex.llm import GeminiLiveVertexLLMService
    from pipecat.services.llm_service import FunctionCallParams
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.workers.runner import WorkerRunner

    model = os.getenv("MODEL", "gemini-live-2.5-flash-native-audio")
    record = CallRecord()
    vad, user_params = turn_settings()

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_in_sample_rate=MIC_SAMPLE_RATE,
            audio_out_enabled=True,
            audio_out_10ms_chunks=2,
        ),
    )

    tools = mission_tools(config)

    llm = GeminiLiveVertexLLMService(
        project_id=get_project_id(),
        location=os.getenv("LOCATION", "us-central1"),
        tools=tools,
        inference_on_context_initialization=config.opener,
        settings=GeminiLiveVertexLLMService.Settings(
            model=model,
            voice=config.voice,
            system_instruction=config.system_instruction,
            temperature=1.0,
            language="en-US",
            vad=vad,
            context_window_compression={"enabled": True},
            enable_affective_dialog=True,
            proactivity=ProactivityConfig(proactive_audio=True),
        ),
    )

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

    if tools is not None:
        llm.register_function("complete_mission", complete_mission)

    @user_aggregator.event_handler("on_user_turn_message_added")
    async def on_user_message(aggregator, message):
        if message.content not in (OPENER_TEXT, opener_text(config.partner)):
            record.add_user(message.content)

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn(aggregator, message):
        record.add_partner(message.content)

    @audiobuffer.event_handler("on_track_audio_data")
    async def on_track_audio(buffer, user_audio, bot_audio, sample_rate, num_channels):
        record.add_mic(user_audio)

    clock = CallClock()
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
        logger.info("Session ended: %s (limit %ss, pause limit %ss)", reason, config.time_limit, pause_limit)
        data = {"type": "time_limit"} if reason == "time_limit" else {"type": "time_limit", "reason": reason}
        await worker.queue_frames([RTVIServerMessageFrame(data=data), EndFrame()])

    # 클라이언트가 sendClientMessage("pause"|"resume")을 보내면 RTVIProcessor가 on_client_message를 부른다.
    @worker.rtvi.event_handler("on_client_message")
    async def on_client_message(rtvi, message):
        if message.type == "pause":
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
        await stop_recording()
        record.paused_sec = clock.paused_total()
        saved = await asyncio.to_thread(finish_call, record, config, model)
        logger.info("Call finished; transcript saved: %s", saved)
        schedule_partner_memory_update(saved, config, record)

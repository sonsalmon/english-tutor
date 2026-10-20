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
    return CallConfig(system_instruction=instruction, mode=mode, voice=voice)


@dataclass
class CallRecord:
    started_at: float = field(default_factory=time.time)
    chunks: List[Tuple[str, str]] = field(default_factory=list)
    mic_pcm: bytearray = field(default_factory=bytearray)
    completed: bool = False
    paused_sec: float = 0.0

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
                "mission": config.mission,
                "completed": record.completed,
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
        transport.output(),
        audiobuffer,
        assistant_aggregator,
    ])
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=False))
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
        if message.content != OPENER_TEXT:
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
            context.add_message({"role": "user", "content": OPENER_TEXT})
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

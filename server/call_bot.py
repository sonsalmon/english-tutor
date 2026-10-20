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

MODES = ("mission", "freetalk", "teachback")
MAX_INSTRUCTION_CHARS = 30_000
MIC_SAMPLE_RATE = 16_000
MIC_MAX_BYTES = MIC_SAMPLE_RATE * 2 * 60 * 30  # 16bit mono, 30분
DEFAULT_VOICE = "Puck"
OPENER_TEXT = "[The learner just joined the call. Start as Ms. Park.]"
TURN_MODE_ENV = "TURN_MODE"
MISSION_RE = re.compile(r'trying to:\s*"([^"]+)"')

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

    def add_user(self, text: str) -> None:
        if text and text.strip():
            self.chunks.append(("Me", text.strip()))

    def add_partner(self, text: str) -> None:
        if text and text.strip():
            self.chunks.append(("Partner", text.strip()))

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
                "duration_sec": int(ended_at - record.started_at),
                "model": model,
                "mission": config.mission,
                "completed": record.completed,
            },
            get_transcript_dir(),
        )
    except Exception as e:  # noqa: BLE001
        logger.error("Transcript save failed: %s", e)
        return None


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
    from pipecat.adapters.schemas.function_schema import FunctionSchema
    from pipecat.adapters.schemas.tools_schema import ToolsSchema
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

    tools = ToolsSchema(standard_tools=[
        FunctionSchema(
            name="complete_mission",
            description=COMPLETE_MISSION_DESCRIPTION,
            properties=COMPLETE_MISSION_PROPERTIES,
            required=["score", "feedback_pointers"],
        )
    ])

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
        record.completed = True
        await worker.queue_frames([RTVIServerMessageFrame(data={"type": "mission_complete", "args": params.arguments})])
        await params.result_callback({"status": "recorded"})

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

    async def end_at_time_limit():
        await asyncio.sleep(config.time_limit)
        logger.info("Session time limit reached (%ss)", config.time_limit)
        await worker.queue_frames([RTVIServerMessageFrame(data={"type": "time_limit"}), EndFrame()])

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
        saved = await asyncio.to_thread(finish_call, record, config, model)
        logger.info("Call finished; transcript saved: %s", saved)

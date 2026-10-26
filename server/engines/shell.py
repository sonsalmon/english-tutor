"""실험 엔진(openai_live·cascade_flux)용 통화 껍데기.

엔진 모듈이 EngineParts(llm·stt·tts)를 건네면 이 껍데기가 전송·집계기·녹음·시계·pause/resume/telemetry·통화 마무리를 맡는다.
기본 경로(call_bot.run_bot)에서 코드를 옮기지 않고 새로 썼다(2026-10-26 설계 결정 3: 기본 경로 바이트 동일 보장).
실험 엔진은 도구를 등록하지 않고, 통화 중 공유는 ok=false(reason=engine)로 답하며, 생각 중·마이크 알림은 내지 않는다.
"""

import asyncio
import logging
import time
from typing import Optional

from server import call_bot, call_tools
from server.engines.base import EngineParts

logger = logging.getLogger(__name__)


async def run_engine_call(webrtc_connection, config, parts: EngineParts) -> None:
    from pipecat.frames.frames import EndFrame, LLMRunFrame
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.pipeline.worker import PipelineParams, PipelineWorker
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair
    from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
    from pipecat.processors.frameworks.rtvi.frames import RTVIServerMessageFrame
    from pipecat.transports.base_transport import TransportParams
    from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
    from pipecat.workers.runner import WorkerRunner

    record = call_bot.CallRecord()
    logger.info("Engine %s for %s: model %s", config.engine, config.mode, parts.model_name)

    transport_kwargs = {}
    if parts.audio_out_sample_rate:
        transport_kwargs["audio_out_sample_rate"] = parts.audio_out_sample_rate
    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_in_enabled=True,
            audio_in_sample_rate=call_bot.MIC_SAMPLE_RATE,
            audio_in_filter=call_bot.build_audio_in_filter(),
            audio_out_enabled=True,
            audio_out_10ms_chunks=2,
            **transport_kwargs,
        ),
    )

    context = LLMContext()
    pair_kwargs = {}
    if parts.realtime_service_mode:
        pair_kwargs["realtime_service_mode"] = True
    if parts.user_params is not None:
        pair_kwargs["user_params"] = parts.user_params
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context, **pair_kwargs)
    audiobuffer = AudioBufferProcessor(sample_rate=call_bot.MIC_SAMPLE_RATE, num_channels=1)

    pipeline = Pipeline([
        transport.input(),
        *([parts.stt] if parts.stt is not None else []),
        user_aggregator,
        parts.llm,
        call_bot.make_usage_collector(record.usage),
        *([parts.tts] if parts.tts is not None else []),
        transport.output(),
        audiobuffer,
        assistant_aggregator,
    ])
    worker = PipelineWorker(pipeline, params=PipelineParams(enable_metrics=True, enable_usage_metrics=True))
    runner = WorkerRunner(handle_sigint=False)
    await runner.add_workers(worker)

    @user_aggregator.event_handler("on_user_turn_message_added")
    async def on_user_message(aggregator, message):
        if message.content not in (call_bot.OPENER_TEXT, call_bot.opener_text(config.partner)):
            record.add_user(message.content)

    @assistant_aggregator.event_handler("on_assistant_turn_stopped")
    async def on_assistant_turn(aggregator, message):
        record.add_partner(message.content)

    @audiobuffer.event_handler("on_track_audio_data")
    async def on_track_audio(buffer, user_audio, bot_audio, sample_rate, num_channels):
        record.add_mic(user_audio)

    clock = call_bot.CallClock()
    pause_limit = call_bot.pause_limit_from_env()
    clock_changed = asyncio.Event()

    async def end_at_time_limit():
        while True:
            clock_changed.clear()
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

    @worker.rtvi.event_handler("on_client_message")
    async def on_client_message(rtvi, message):
        if message.type == "share":
            data = message.data if isinstance(message.data, dict) else {}
            text = call_tools.clean_share_text(data.get("text"))
            if text:
                record.add_note("Me (shared)", call_tools.share_record_text(text, None))
            await rtvi.send_server_message({"type": "share_ack", "id": data.get("id"), "ok": False, "reason": "engine"})
        elif message.type == "telemetry":
            line = call_bot.format_telemetry(message.data)
            if line:
                logger.info("Telemetry [%s %s %s] %s", config.engine, config.partner or "park", config.mode, line)
        elif message.type == "pause":
            if clock.pause():
                clock_changed.set()
                await rtvi.interrupt_bot()
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
            context.add_message({"role": "user", "content": call_bot.opener_text(config.partner)})
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
        saved = await asyncio.to_thread(call_bot.finish_call, record, config, parts.model_name, None, None)
        logger.info("Call finished; transcript saved: %s", saved)
        call_bot.schedule_partner_memory_update(saved, config, record)
        call_bot.notify_call_saved(saved, config, record)

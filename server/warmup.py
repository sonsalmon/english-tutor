"""서버가 뜰 때 첫 통화가 처음 부르는 무거운 import와 모델을 미리 불러 둔다.

재시작 뒤 첫 통화만 offer에서 Gemini 연결까지 약 5.4초 걸렸다(운영 2026-10-27 09:38, 이후 통화는 0.4초).
그 시간은 WebRTC 첫 연결 준비, Pipecat 통화 모듈 import, RNNoise, Vertex 인증 첫 갱신,
Smart Turn·Silero ONNX 세션 첫 생성이었다. 같은 일을 서버 시작 때 한 번 해 두면 첫 통화도 데워진 상태로 시작한다.

단계마다 실패해도 경고만 남기고 다음 단계로 간다. 전체가 WARMUP_TIMEOUT_SEC를 넘거나 실패해도 서버는 뜬다.
`CALL_WARMUP=off`로 끈다."""

import asyncio
import importlib
import logging
import os
import time
from typing import Callable, Dict, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

WARMUP_ENV = "CALL_WARMUP"
WARMUP_TIMEOUT_SEC = 30.0

# run_bot·turn_settings·live_service_class·build_noise_filter가 통화 안에서 처음 import하는 모듈.
CALL_MODULES = (
    "aiortc",
    "pipecat.pipeline.pipeline",
    "pipecat.pipeline.worker",
    "pipecat.processors.aggregators.llm_context",
    "pipecat.processors.aggregators.llm_response_universal",
    "pipecat.processors.audio.audio_buffer_processor",
    "pipecat.processors.frameworks.rtvi.frames",
    "pipecat.services.google.gemini_live.llm",
    "pipecat.services.google.gemini_live.vertex.llm",
    "pipecat.services.llm_service",
    "pipecat.transports.smallwebrtc.transport",
    "pipecat.workers.runner",
    "pipecat.turns.user_stop",
    "pipecat.turns.user_turn_strategies",
    "pipecat.audio.turn.smart_turn.local_smart_turn_v3",
    "pipecat.audio.vad.silero",
    "google.auth.transport.requests",
)


def warmup_enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return (env.get(WARMUP_ENV) or "on").strip().lower() not in ("off", "0", "false", "no")


def _imports() -> None:
    for name in CALL_MODULES:
        importlib.import_module(name)


def _webrtc() -> None:
    """서버 쪽 연결 준비(offer 받기·answer 만들기)를 한 번 해 둔다. 운영 첫 통화에서 0.67초, 이후 2ms였다."""
    from aiortc import RTCBundlePolicy, RTCConfiguration, RTCPeerConnection

    async def offer_answer():
        # 서버(SmallWebRTCConnection)와 같은 설정. 기본값은 공개 STUN 서버를 물어 수집이 10초까지 걸린다.
        config = RTCConfiguration(iceServers=[], bundlePolicy=RTCBundlePolicy.MAX_BUNDLE)
        caller, callee = RTCPeerConnection(config), RTCPeerConnection(config)
        try:
            caller.addTransceiver("audio")
            await caller.setLocalDescription(await caller.createOffer())
            await callee.setRemoteDescription(caller.localDescription)
            await callee.setLocalDescription(await callee.createAnswer())
        finally:
            await caller.close()
            await callee.close()

    asyncio.run(offer_answer())


def _live_service() -> None:
    from server import call_bot

    call_bot.live_service_class()


def _noise_filter() -> None:
    from server import call_bot

    call_bot.build_noise_filter()


def _vertex_auth() -> None:
    """Gemini Live(Vertex) 서비스가 통화마다 하는 인증 조회·토큰 갱신을 한 번 해 둔다. 토큰 값은 쓰지도 남기지도 않는다."""
    import google.auth
    from google.auth.transport.requests import Request

    from server.config_utils import get_project_id

    get_project_id()
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(Request())


def _smart_turn() -> None:
    from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

    LocalSmartTurnAnalyzerV3()


def _silero() -> None:
    from server import barge_in

    barge_in.make_analyzer()


def _breaths() -> None:
    from server import breath_insert

    if not breath_insert.breaths_enabled():
        return
    for voice_dir in sorted(p for p in breath_insert.ASSET_DIR.iterdir() if p.is_dir()):
        breath_insert.load_clips(voice_dir.name)


CALL_WARMUP_STEPS: Tuple[Tuple[str, Callable[[], None]], ...] = (
    ("imports", _imports),
    ("webrtc", _webrtc),
    ("live_service", _live_service),
    ("noise_filter", _noise_filter),
    ("vertex_auth", _vertex_auth),
    ("smart_turn", _smart_turn),
    ("silero", _silero),
    ("breaths", _breaths),
)


def warm_call_path(steps: Optional[Sequence[Tuple[str, Callable[[], None]]]] = None,
                   clock: Callable[[], float] = time.perf_counter) -> Dict[str, Union[float, str]]:
    """단계를 차례로 돌려 {단계: 걸린 초 또는 'error: ...'}를 돌려준다. 한 단계가 실패해도 나머지는 돈다."""
    results: Dict[str, Union[float, str]] = {}
    for name, step in CALL_WARMUP_STEPS if steps is None else steps:
        start = clock()
        try:
            step()
            results[name] = round(clock() - start, 3)
        except Exception as exc:
            results[name] = f"error: {type(exc).__name__}: {exc}"
            logger.warning("Call warmup step %s failed: %s", name, results[name])
    logger.info("Call warmup done: %s", ", ".join(
        f"{k} {v:.2f}s" if isinstance(v, float) else f"{k} FAILED" for k, v in results.items()))
    return results


async def warm_on_startup(env=None, timeout: float = WARMUP_TIMEOUT_SEC,
                          warm: Optional[Callable[[], object]] = None) -> None:
    """lifespan에서 부른다. 꺼져 있으면 건너뛰고, 실패하거나 timeout을 넘겨도 예외 없이 돌아온다."""
    if not warmup_enabled(env):
        logger.info("Call warmup off (%s)", WARMUP_ENV)
        return
    started = time.perf_counter()
    try:
        await asyncio.wait_for(asyncio.to_thread(warm or warm_call_path), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("Call warmup did not finish in %.0fs; starting the server anyway", timeout)
    except Exception as exc:
        logger.warning("Call warmup failed; starting the server anyway: %s", exc)
    else:
        logger.info("Call warmup took %.2fs before the server started", time.perf_counter() - started)

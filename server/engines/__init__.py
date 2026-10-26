"""통화 엔진 스위치. 실험 엔진 모듈은 지연 import한다(이 패키지는 pipecat을 불러오지 않는다)."""

import importlib
import logging

from server.engines.base import ENGINE_MODULES, ENGINE_NOT_READY, EngineParts, engine_unavailable_reason

logger = logging.getLogger(__name__)

# 엔진 이름 -> 모듈 경로. 모듈은 `build_parts(config) -> EngineParts`를 가진다.
ENGINES = ENGINE_MODULES


async def run_engine(webrtc_connection, config) -> None:
    """call_bot.run_bot이 Gemini가 아닌 엔진 요청을 넘겨 오는 곳. 엔진 모듈이 서비스 묶음을 만들고 shell이 통화를 돌린다."""
    try:
        module = importlib.import_module(ENGINES[config.engine])
        parts = module.build_parts(config)
    except Exception:
        logger.exception("Engine %s could not start", config.engine)
        disconnect = getattr(webrtc_connection, "disconnect", None)
        if disconnect is not None:
            try:
                await disconnect()
            except Exception:  # noqa: BLE001 - 이미 실패 처리 중이다
                logger.warning("Disconnect after engine failure also failed", exc_info=True)
        return
    from server.engines import shell

    await shell.run_engine_call(webrtc_connection, config, parts)


__all__ = ["ENGINES", "ENGINE_NOT_READY", "EngineParts", "engine_unavailable_reason", "run_engine"]

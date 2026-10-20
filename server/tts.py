"""파트너 한 줄을 통화와 같은 Gemini 목소리로 읽어 WAV로 돌려준다(Vertex AI Gemini TTS).

- 모델 id는 상수 TTS_MODEL이고 환경변수 TTS_MODEL로 바꾼다. 환경변수가 없고 기본 모델이 거절되면 FALLBACK_MODELS를 차례로 시도한다.
- 같은 (모델, 목소리, 문장)은 TTS_DIR(기본 ~/dev/learning/english/tts-cache)의 파일로 다시 쓴다. 두 번째부터는 모델을 부르지 않는다.
- Gemini TTS는 24000Hz 16비트 모노 PCM을 주므로 WAV 머리글을 붙인다.
"""

import hashlib
import logging
import os
import re
import struct
import tempfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

TTS_DIR_ENV = "TTS_DIR"
DEFAULT_TTS_DIR = "~/dev/learning/english/tts-cache"
TTS_MODEL_ENV = "TTS_MODEL"
DEFAULT_TTS_MODEL = "gemini-2.5-flash-tts"
FALLBACK_MODELS = ("gemini-2.5-flash-preview-tts", "gemini-2.5-pro-tts")
TTS_MODEL = os.getenv(TTS_MODEL_ENV) or DEFAULT_TTS_MODEL

SAMPLE_RATE = 24000
MAX_TEXT_CHARS = 500
VOICE_RE = re.compile(r"[A-Za-z]+", re.ASCII)


class TTSError(Exception):
    """모델 호출이 실패했거나 오디오가 없을 때."""


def get_tts_dir() -> Path:
    return Path(os.getenv(TTS_DIR_ENV, DEFAULT_TTS_DIR)).expanduser()


def validate(text: str, voice: str) -> None:
    if not isinstance(voice, str) or not VOICE_RE.fullmatch(voice):
        raise ValueError("voice must be alphabetic")
    if not isinstance(text, str) or not (1 <= len(text) <= MAX_TEXT_CHARS):
        raise ValueError(f"text must be 1..{MAX_TEXT_CHARS} chars")


def pcm_to_wav(pcm: bytes, sample_rate: int = SAMPLE_RATE) -> bytes:
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
    header += b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, sample_rate, sample_rate * 2, 2, 16)
    header += b"data" + struct.pack("<I", len(pcm))
    return header + pcm


def cache_key(model: str, voice: str, text: str) -> str:
    return hashlib.sha256(f"{model}\n{voice}\n{text}".encode("utf-8")).hexdigest()


def _make_client() -> Any:
    from server.tutor import _make_client as make

    return make()


def _extract_pcm(response: Any) -> tuple:
    try:
        part = response.candidates[0].content.parts[0]
        data = part.inline_data.data
        mime = getattr(part.inline_data, "mime_type", "") or ""
    except (AttributeError, IndexError, TypeError) as exc:
        raise TTSError("model returned no audio") from exc
    if not data:
        raise TTSError("model returned no audio")
    match = re.search(r"rate=(\d+)", mime)
    return bytes(data), int(match.group(1)) if match else SAMPLE_RATE


def _call(client: Any, model: str, text: str, voice: str) -> bytes:
    from google.genai import types

    config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))
        ),
    )
    response = client.models.generate_content(model=model, contents=text, config=config)
    pcm, rate = _extract_pcm(response)
    return pcm_to_wav(pcm, rate)


def synthesize(text: str, voice: str, client: Optional[Any] = None) -> bytes:
    """text를 voice 목소리로 읽은 WAV 바이트. 같은 입력은 디스크 캐시에서 돌려준다."""
    validate(text, voice)
    global TTS_MODEL
    cache_dir = get_tts_dir()
    models = [TTS_MODEL]
    if not os.getenv(TTS_MODEL_ENV):
        models += [m for m in (DEFAULT_TTS_MODEL, *FALLBACK_MODELS) if m != TTS_MODEL]
    # 모델을 부르기 전에 후보 모델 키를 모두 조회한다(폴백 캐시가 재시작 뒤에도 쓰이게).
    for model in models:
        cached = cache_dir / f"{cache_key(model, voice, text)}.wav"
        if cached.is_file():
            return cached.read_bytes()
    client = client or _make_client()
    last: Optional[Exception] = None
    for model in models:
        try:
            wav = _call(client, model, text, voice)
        except Exception as exc:
            logger.warning("TTS model %s failed: %s", model, exc)
            last = exc
            continue
        TTS_MODEL = model
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"{cache_key(model, voice, text)}.wav"
        fd, tmp = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        with os.fdopen(fd, "wb") as handle:
            handle.write(wav)
        os.replace(tmp, path)
        return wav
    raise TTSError(f"all TTS models failed: {last}") from last

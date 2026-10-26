"""입력 이득 단 (묶음 4 P3, docs/engines.md).

폰을 입에서 떼고 말하면 학습자 소리가 약 9 dB 작아 Gemini의 말 시작 감지가 놓친다. 전송 계층에서 말소리만
목표 레벨(-20 dBFS)로 끌어올린다. 잡음은 키우지 않는다(바닥 상한), 디지털 무음은 그대로 둔다.
이득 → RNNoise 순서로 체인에 건다. `LIVE_INPUT_GAIN=off`면 이 모듈은 쓰이지 않는다."""

import logging
import math
import os
from typing import List, Optional

import numpy as np
from pipecat.audio.filters.base_audio_filter import BaseAudioFilter

logger = logging.getLogger(__name__)

INPUT_GAIN_ENV = "LIVE_INPUT_GAIN"  # auto|off
TARGET_ENV = "LIVE_INPUT_GAIN_TARGET_DBFS"
MAX_DB_ENV = "LIVE_INPUT_GAIN_MAX_DB"
GATE_ENV = "LIVE_INPUT_GATE_DBFS"
DEFAULT_TARGET_DBFS = -20.0
DEFAULT_MAX_DB = 18.0
DEFAULT_GATE_DBFS = -50.0
NOISE_CEILING_DBFS = -45.0  # 이득 뒤 잡음 바닥이 이 값을 넘지 않게 이득을 제한한다
PEAK_LIMIT = 10 ** (-1 / 20)  # -1 dBFS
CLIP_KNEE = 0.7
ATTACK_SEC = 0.02
RELEASE_SEC = 1.0
GAIN_UP_SEC = 0.05
GAIN_DOWN_SEC = 0.01  # 큰 소리가 들어오면 이득을 빨리 내려 말 시작이 튀지 않게 한다
FLOOR_SEC = 0.5
LOG_EVERY_SEC = 10.0


def _float_env(env, name: str, default: float, low: float, high: float) -> float:
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = None
    if value is None or not low <= value <= high:
        logger.warning("%s=%r ignored (%s..%s)", name, raw, low, high)
        return default
    return value


def input_gain_settings(env=None) -> Optional[dict]:
    """`LIVE_INPUT_GAIN`(auto|off, 기본 auto). off면 None, 아니면 InputGainFilter 생성자 인자. 잘못된 값은 경고 후 기본값."""
    env = os.environ if env is None else env
    mode = (env.get(INPUT_GAIN_ENV) or "").strip().lower()
    if mode == "off":
        return None
    if mode not in ("", "auto"):
        logger.warning("%s=%r ignored (auto|off)", INPUT_GAIN_ENV, mode)
    return {
        "target_dbfs": _float_env(env, TARGET_ENV, DEFAULT_TARGET_DBFS, -40.0, -3.0),
        "max_db": _float_env(env, MAX_DB_ENV, DEFAULT_MAX_DB, 0.0, 30.0),
        "gate_dbfs": _float_env(env, GATE_ENV, DEFAULT_GATE_DBFS, -80.0, -20.0),
    }


def _db(value: float) -> float:
    return 20 * math.log10(max(value, 1e-9))


class InputGainFilter(BaseAudioFilter):
    """말소리(게이트 이상 프레임)의 포락선을 따라 목표 레벨까지 이득을 준다. 길이가 제각각인 프레임도 받는다."""

    def __init__(self, target_dbfs=DEFAULT_TARGET_DBFS, max_db=DEFAULT_MAX_DB, gate_dbfs=DEFAULT_GATE_DBFS):
        self.target_dbfs = target_dbfs
        self.max_db = max_db
        self.gate_dbfs = gate_dbfs
        self._rate = 16000
        self._env_db: Optional[float] = None  # 말소리 포락선
        self._floor_db: Optional[float] = None  # 잡음 바닥
        self._gain_db = 0.0
        self._log_sec = 0.0
        self._log_in = [0.0, 0, 0.0]  # 제곱합, 표본 수, 최대치
        self._log_out = [0.0, 0, 0.0]

    @property
    def gain_db(self) -> float:
        return self._gain_db

    async def start(self, sample_rate: int):
        self._rate = sample_rate
        logger.info("Input gain auto (target %.0f dBFS, max +%.0f dB, gate %.0f dBFS)",
                    self.target_dbfs, self.max_db, self.gate_dbfs)

    async def stop(self):
        pass

    async def process_frame(self, frame):
        pass

    @staticmethod
    def _follow(current: Optional[float], value: float, dt: float, attack: float, release: float) -> float:
        if current is None:
            return value
        tau = attack if value > current else release
        return current + (value - current) * (1 - math.exp(-dt / tau))

    def _target_gain(self) -> float:
        want = self.target_dbfs - (self._env_db if self._env_db is not None else self.target_dbfs)
        cap = self.max_db
        if self._floor_db is not None:
            cap = min(cap, max(0.0, NOISE_CEILING_DBFS - self._floor_db))
        return min(max(want, 0.0), cap)

    async def filter(self, audio: bytes) -> bytes:
        x = np.frombuffer(audio, dtype=np.int16)
        if x.size == 0 or not x.any():
            return audio  # 디지털 무음은 그대로
        xf = x.astype(np.float32) / 32768.0
        dt = x.size / self._rate
        rms_db = _db(float(np.sqrt(np.mean(xf * xf))))
        if rms_db >= self.gate_dbfs:
            first = self._env_db is None
            self._env_db = self._follow(self._env_db, rms_db, dt, ATTACK_SEC, RELEASE_SEC)
            if first:
                self._gain_db = self._target_gain()  # 첫 말소리는 이득이 오르기를 기다리지 않는다
        else:
            self._floor_db = self._follow(self._floor_db, rms_db, dt, FLOOR_SEC, FLOOR_SEC)
        target = self._target_gain()
        tau = GAIN_DOWN_SEC if target < self._gain_db else GAIN_UP_SEC
        self._gain_db += (target - self._gain_db) * (1 - math.exp(-dt / tau))
        out = audio
        if self._gain_db > 0.05:
            y = xf * (10 ** (self._gain_db / 20))
            mag = np.abs(y)
            over = mag > CLIP_KNEE  # tanh 소프트 클립: 무릎 위만 -1 dBFS 안으로 눌러 담는다
            y[over] = np.sign(y[over]) * (CLIP_KNEE + (PEAK_LIMIT - CLIP_KNEE) * np.tanh((mag[over] - CLIP_KNEE) / (PEAK_LIMIT - CLIP_KNEE)))
            out = np.clip(np.rint(y * 32768.0), -32768, 32767).astype(np.int16).tobytes()
        self._observe(xf, np.frombuffer(out, dtype=np.int16).astype(np.float32) / 32768.0, dt)
        return out

    def _observe(self, xin, xout, dt: float) -> None:
        for acc, x in ((self._log_in, xin), (self._log_out, xout)):
            acc[0] += float(np.sum(x * x))
            acc[1] += x.size
            acc[2] = max(acc[2], float(np.abs(x).max()))
        self._log_sec += dt
        if self._log_sec < LOG_EVERY_SEC:
            return
        (si, ni, pi), (so, no, po) = self._log_in, self._log_out
        logger.info("Input gain: in rms %.1f peak %.1f dBFS -> out rms %.1f peak %.1f dBFS (gain %.1f dB, floor %s dBFS)",
                    _db(math.sqrt(si / max(ni, 1))), _db(pi), _db(math.sqrt(so / max(no, 1))), _db(po), self._gain_db,
                    "n/a" if self._floor_db is None else f"{self._floor_db:.1f}")
        self._log_sec, self._log_in, self._log_out = 0.0, [0.0, 0, 0.0], [0.0, 0, 0.0]


class ChainAudioFilter(BaseAudioFilter):
    """여러 입력 필터를 차례로 건다(앞 필터의 출력이 다음 필터의 입력)."""

    def __init__(self, filters: List[BaseAudioFilter]):
        self.filters = list(filters)

    async def start(self, sample_rate: int):
        for f in self.filters:
            await f.start(sample_rate)

    async def stop(self):
        for f in self.filters:
            await f.stop()

    async def process_frame(self, frame):
        for f in self.filters:
            await f.process_frame(frame)

    async def filter(self, audio: bytes) -> bytes:
        for f in self.filters:
            audio = await f.filter(audio)
        return audio

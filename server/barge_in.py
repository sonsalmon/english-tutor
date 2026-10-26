"""로컬 끼어들기 게이트 (묶음 4 P1, docs/engines.md).

3.8은 자기 차례와 겹친 학습자 음성을 전사하지 않아 "낱말 세기"가 발동하지 않는다. 그래서 상대가 말하는 동안
마이크를 Silero VAD로 직접 듣고, 유성음이 `min_voiced_ms` 이상 이어지면 끼어든 것으로 본다.
짧은 맞장구("Mm.", "Hmm")는 이 길이에 못 미쳐 상대를 멈추지 않는다."""

from typing import Optional

import numpy as np

SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 512  # Silero 16 kHz 창
WINDOW_MS = WINDOW_SAMPLES * 1000 // SAMPLE_RATE
DEFAULT_MIN_VOICED_MS = 700
DEFAULT_CONFIDENCE = 0.7
DEFAULT_MIN_DBFS = -40.0
DEFAULT_BRIDGE_MS = 200


def make_analyzer():
    from pipecat.audio.vad.silero import SileroVADAnalyzer

    analyzer = SileroVADAnalyzer(sample_rate=SAMPLE_RATE)
    analyzer.set_sample_rate(SAMPLE_RATE)  # 생성자 인자만으로는 sample_rate가 0이라 모든 창이 오류로 신뢰도 0이 된다
    return analyzer


class VoiceRun:
    """512샘플 창마다 Silero 신뢰도를 재서, 이어진 유성음 길이(run_ms)를 센다. bridge_ms 이하의 끊김은 잇는다."""

    def __init__(self, analyzer=None, confidence: float = DEFAULT_CONFIDENCE, min_dbfs: Optional[float] = DEFAULT_MIN_DBFS,
                 bridge_ms: int = DEFAULT_BRIDGE_MS):
        self._analyzer = analyzer or make_analyzer()
        self.confidence = confidence
        self.min_dbfs = min_dbfs
        self.bridge_ms = bridge_ms
        self.audio_ms = 0  # 지금까지 넣은 오디오 길이(시험·로그용)
        model = getattr(self._analyzer, "_model", None)
        if model is not None:
            model.reset_states()
        self.reset()

    def reset(self) -> None:
        self._buf = b""
        self.run_ms = 0
        self._gap_ms = 0

    def _voiced(self, window: bytes) -> bool:
        # 조용한 창도 모델에 넣는다. Silero는 연속 입력을 전제로 해서, 배경을 본 뒤에야 말 시작을 빨리 잡는다.
        confident = float(np.asarray(self._analyzer.voice_confidence(window)).ravel()[0]) >= self.confidence
        if not confident or self.min_dbfs is None:
            return confident
        peak = int(np.abs(np.frombuffer(window, dtype=np.int16).astype(np.int32)).max())
        return peak > 0 and 20 * np.log10(peak / 32768) >= self.min_dbfs

    def feed(self, pcm: bytes) -> int:
        """16 kHz 모노 int16 오디오를 넣고 현재 run_ms를 돌려준다."""
        self._buf += pcm
        size = WINDOW_SAMPLES * 2
        while len(self._buf) >= size:
            window, self._buf = self._buf[:size], self._buf[size:]
            self.audio_ms += WINDOW_MS
            if self._voiced(window):
                self.run_ms += self._gap_ms + WINDOW_MS
                self._gap_ms = 0
            else:
                self._gap_ms += WINDOW_MS
                if self._gap_ms > self.bridge_ms:
                    self.run_ms = 0
                    self._gap_ms = 0
        return self.run_ms


class BargeInGate(VoiceRun):
    """유성음이 min_voiced_ms 이상 이어지는 순간 True를 한 번 돌려준다. reset() 전에는 다시 울리지 않는다."""

    def __init__(self, analyzer=None, min_voiced_ms: int = DEFAULT_MIN_VOICED_MS, confidence: float = DEFAULT_CONFIDENCE,
                 min_dbfs: float = DEFAULT_MIN_DBFS, bridge_ms: int = DEFAULT_BRIDGE_MS):
        self.min_voiced_ms = min_voiced_ms
        super().__init__(analyzer, confidence, min_dbfs, bridge_ms)

    def reset(self) -> None:
        super().reset()
        self.fired = False

    def feed(self, pcm: bytes) -> bool:
        if self.fired:
            return False
        if super().feed(pcm) >= self.min_voiced_ms:
            self.fired = True
            return True
        return False

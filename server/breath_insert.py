"""파트너 출력 오디오에 사전 생성한 들숨 클립을 끼워 넣는 처리기(실험 스위치 LIVE_BREATHS, 기본 꺼짐).

라이브 모델은 숨소리 태그를 받지 않으므로(docs/breaths.md), scripts/make_breath_clips.py가 만든 짧은 클립을
파트너 말소리 바로 앞에 끼운다. 놓는 자리 규칙이 개수보다 중요하다.

- 학습자 말에 답하는 파트너 차례의 첫 말소리 직전, 또는 긴 차례 안에서 문장 끝으로 보이는 쉼(0.35초 이상) 뒤 말소리 직전.
- 학습자가 말하는 중에는 넣지 않는다. 마지막 삽입 뒤 15초 안에는 넣지 않는다.
- 파트너 말 1분당 약 2회가 되도록 예산을 둔다(삽입 수 + 1 <= 2 x (말한 분 + 앞으로 말할 차례 6초) + 통화마다 뽑는 0~1 무작위 값).
  통화는 짧아서(파트너 말 5~18초) 고정 문턱이면 첫 삽입이 영영 안 나온다. 무작위 값이 문턱을 통화마다 흩어 평균을 분당 2회에 맞춘다.
  한 번에 늘어나는 시간은 0.35초 이하다.
"""
import logging
import os
import random
import time
import wave
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

BREATHS_ENV = "LIVE_BREATHS"
ASSET_DIR = Path(__file__).resolve().parent / "assets" / "breaths"
FALLBACK_VOICE = "Kore"
CLIP_RATE = 24000
NOMINAL_SPEECH_DB = -20.0  # 클립이 저장된 기준 말소리 크기(scripts/make_breath_clips.py와 같은 값)
SUB_SEC = 0.01
SPEECH_DB = -48.0  # 10 ms 프레임이 이보다 크면 말소리(파트너 쉼의 잡음은 약 -60 dBFS)
BRIDGE_SEC = 0.15  # 이보다 짧은 쉼(단어 사이)은 같은 구절로 본다
MIN_PAUSE_SEC = 0.35
MIN_PHRASE_SEC = 1.2
MIN_TURN_SPEECH_SEC = 4.0
MIN_GAP_SEC = 15.0
TARGET_PER_MIN = 2.0
TURN_LOOKAHEAD_SEC = 6.0  # 지금 시작하는 차례에서 곧 말할 분량의 선불(학습자 말에 답하는 차례의 중앙값 길이)
MAX_ADD_SEC = 0.35
LEARNER_LOUD_PEAK = 600
LEARNER_HOLD_SEC = 0.6
LEARNER_MIN_LOUD_FRAMES = 10
REF_WINDOW = 400
MAX_GAIN_DB = 15.0


def breaths_enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return (env.get(BREATHS_ENV) or "").strip().lower() in ("on", "1", "true", "yes")


def load_clips(voice: str, root: Path = ASSET_DIR) -> List[np.ndarray]:
    for name in (voice, FALLBACK_VOICE):
        clips = []
        for path in sorted((root / name).glob("b*.wav")):
            with wave.open(str(path)) as w:
                if w.getframerate() == CLIP_RATE and w.getnchannels() == 1:
                    clips.append(np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64))
        if clips:
            return clips
    return []


class BreathPlanner:
    """오디오 조각을 받아 (끼운 뒤의) 오디오 조각 목록을 돌려준다. pipecat에 의존하지 않아 단독으로 시험한다."""

    def __init__(self, clips: List[np.ndarray], rng: Optional[random.Random] = None,
                 clock: Callable[[], float] = time.monotonic, credit: Optional[float] = None):
        self.clips = clips
        self.rng = rng or random.Random()
        self.clock = clock
        self.credit = self.rng.random() if credit is None else credit
        self.events: List[dict] = []
        self.inserted = 0
        self.total_speech = 0.0
        self.last_insert_at: Optional[float] = None
        self.last_clip = -1
        self.last_gain_db = 0.0
        self._ref_db: List[float] = []
        self._learner_last_loud: Optional[float] = None
        self._learner_loud_frames = 0
        self._learner_flag = False
        self._answers = False
        self._answer_pending = False
        self._in_turn = False
        self._reset_turn()

    def _reset_turn(self) -> None:
        self.turn_speech = 0.0
        self.silent = 0.0
        self.phrase = 0.0
        self._prev_phrase = 0.0
        self.turn_started_at = 0.0
        self.first_onset_done = False

    def learner_audio(self, peak: int) -> None:
        if peak > LEARNER_LOUD_PEAK:
            self._learner_last_loud = self.clock()
            self._learner_loud_frames += 1
            if self._learner_loud_frames >= LEARNER_MIN_LOUD_FRAMES:
                self._answer_pending = True

    def learner_started(self) -> None:
        self._learner_flag = True
        self._answer_pending = True

    def learner_stopped(self) -> None:
        self._learner_flag = False

    def learner_idle(self, now: float) -> float:
        """마지막 학습자 큰 소리 뒤 경과 초. 큰 소리가 한 번도 없었으면 -1."""
        return -1.0 if self._learner_last_loud is None else now - self._learner_last_loud

    def learner_speaking(self) -> bool:
        if self._learner_flag:
            return True
        return self._learner_last_loud is not None and self.clock() - self._learner_last_loud < LEARNER_HOLD_SEC

    def turn_started(self) -> None:
        self._reset_turn()
        self._in_turn = True
        self._answers = self._answer_pending
        self._answer_pending = False
        self._learner_loud_frames = 0
        self.turn_started_at = self.clock()

    def turn_ended(self) -> None:
        self._in_turn = False

    def _gain(self) -> float:
        if len(self._ref_db) < 100:
            return 1.0
        ref = float(np.percentile(self._ref_db, 90))
        return 10 ** (max(-MAX_GAIN_DB, min(MAX_GAIN_DB, ref - NOMINAL_SPEECH_DB)) / 20)

    def _allowed(self, kind: str, now: float) -> bool:
        if not self.clips or self.learner_speaking():
            return False
        if self.last_insert_at is not None and now - self.last_insert_at < MIN_GAP_SEC:
            return False
        if self.inserted + 1 > TARGET_PER_MIN * (self.total_speech + TURN_LOOKAHEAD_SEC) / 60 + self.credit:
            return False
        if kind == "start":
            return self._answers
        return self.turn_speech >= MIN_TURN_SPEECH_SEC

    def _pick(self, sample_rate: int) -> bytes:
        choices = [i for i in range(len(self.clips)) if i != self.last_clip] or [0]
        self.last_clip = self.rng.choice(choices)
        gain = self._gain()
        self.last_gain_db = 20 * np.log10(gain)
        clip = self.clips[self.last_clip][: int(MAX_ADD_SEC * CLIP_RATE)] * gain
        if sample_rate != CLIP_RATE:
            n = int(len(clip) * sample_rate / CLIP_RATE)
            clip = np.interp(np.linspace(0, len(clip) - 1, n), np.arange(len(clip)), clip)
        return np.clip(clip, -32768, 32767).astype(np.int16).tobytes()

    def process_audio(self, pcm: bytes, sample_rate: int) -> List[bytes]:
        """pcm(16비트 모노)을 그대로 돌려주거나, 말소리 시작 직전에 클립을 끼워 여러 조각으로 나눠 돌려준다."""
        step = int(sample_rate * SUB_SEC) * 2
        out: List[bytes] = []
        start = 0
        for pos in range(0, len(pcm) - step + 1, step):
            x = np.frombuffer(pcm, dtype=np.int16, count=step // 2, offset=pos).astype(np.float64)
            db = 10 * np.log10(float(np.mean(x ** 2)) + 1e-9) - 20 * np.log10(32768.0)
            if db <= SPEECH_DB:
                self.silent += SUB_SEC
                if self.phrase > 0.0 and self.silent >= BRIDGE_SEC:
                    self._prev_phrase, self.phrase = self.phrase, 0.0
                continue
            if self.phrase == 0.0:
                kind = None
                if not self.first_onset_done:
                    kind = "start"
                elif self.silent >= MIN_PAUSE_SEC and self._prev_phrase >= MIN_PHRASE_SEC:
                    kind = "pause"
                self.first_onset_done = True
                now = self.clock()
                if kind and self._allowed(kind, now):
                    out.append(pcm[start:pos])
                    out.append(self._pick(sample_rate))
                    start = pos
                    self.inserted += 1
                    self.last_insert_at = now
                    self.events.append(dict(kind=kind, clip=self.last_clip, pause=self.silent, turn_speech=self.turn_speech,
                                            total_speech=self.total_speech, gain_db=self.last_gain_db, learner_idle=self.learner_idle(now)))
            self.silent = 0.0
            self.phrase += SUB_SEC
            self.turn_speech += SUB_SEC
            self.total_speech += SUB_SEC
            self._ref_db.append(db)
            if len(self._ref_db) > REF_WINDOW:
                del self._ref_db[0]
        if not out:
            return [pcm]
        out.append(pcm[start:])
        return [chunk for chunk in out if chunk]


def make_breath_processor(voice: str, root: Path = ASSET_DIR):
    """LLM 서비스 뒤, transport.output() 앞에 두는 FrameProcessor. 클립이 없으면 None."""
    from dataclasses import replace

    from pipecat.frames.frames import (
        InputAudioRawFrame,
        InterruptionFrame,
        LLMFullResponseEndFrame,
        TTSAudioRawFrame,
        TTSStartedFrame,
        TTSStoppedFrame,
        UserStartedSpeakingFrame,
        UserStoppedSpeakingFrame,
    )
    from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

    clips = load_clips(voice, root)
    if not clips:
        logger.warning("LIVE_BREATHS is on but no breath clips were found for voice %s", voice)
        return None
    planner = BreathPlanner(clips)

    class BreathInserter(FrameProcessor):
        async def process_frame(self, frame, direction):
            await super().process_frame(frame, direction)
            if isinstance(frame, InputAudioRawFrame):
                samples = np.frombuffer(frame.audio, dtype=np.int16)
                planner.learner_audio(int(np.abs(samples.astype(np.int32)).max()) if samples.size else 0)
            elif isinstance(frame, UserStartedSpeakingFrame):
                planner.learner_started()
            elif isinstance(frame, UserStoppedSpeakingFrame):
                planner.learner_stopped()
            elif isinstance(frame, TTSStartedFrame):
                planner.turn_started()
            elif isinstance(frame, (TTSStoppedFrame, LLMFullResponseEndFrame, InterruptionFrame)):
                planner.turn_ended()
            elif isinstance(frame, TTSAudioRawFrame) and frame.num_channels == 1:
                seen = len(planner.events)
                chunks = planner.process_audio(frame.audio, frame.sample_rate)
                if len(chunks) > 1:
                    for event in planner.events[seen:]:
                        logger.info("Breath inserted (%s): clip %d, %.2fs pause, %.1fs into the turn, %.1fs partner speech so far, gain %+.1f dB, %.1fs since learner sound",
                                    event["kind"], event["clip"], event["pause"], event["turn_speech"], event["total_speech"], event["gain_db"], event["learner_idle"])
                    for chunk in chunks:
                        await self.push_frame(replace(frame, audio=chunk), direction)
                    return
            await self.push_frame(frame, direction)

    return BreathInserter()

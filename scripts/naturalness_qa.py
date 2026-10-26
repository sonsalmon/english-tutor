"""대화 자연스러움 자동 시험(N01~N08). aiortc 가짜 브라우저가 통화에 걸어 학습자의 실제 목소리 클립을 정해진 시각표대로 재생하고,
파트너(상대 음성)를 시각과 함께 녹음해 차례 넘기기 지표를 잰다. 시나리오 정의는 replica/test-plan.md가 정본이다.

예) 임시 서버(8981)를 띄운 뒤:
  python scripts/naturalness_qa.py --url http://127.0.0.1:8981 --transcript-dir $TRANSCRIPT_DIR \
      --out-dir <점수 폴더> --name baseline-gemini-live --partner jake
엔진을 고르는 서버는 --engine 값을 request_data.engine으로 받는다(엔진 구분이 없는 서버는 모르는 키를 무시한다).
모든 시각은 내 마이크 첫 프레임이 나간 순간을 0으로 센 초다.
"""
import argparse
import asyncio
import fractions
import json
import os
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

import aiohttp
import numpy as np
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame
from av.audio.resampler import AudioResampler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import naturalness_metrics as M  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CLIPS_DIR = "/Users/sonsalmom/dev/.omo/dag/night-3/replica/learner-clips"
SR = 16000
FRAME = 320
GREETING_TIMEOUT_S = 40.0
REPLY_TIMEOUT_S = 25.0
TURN_END_QUIET_S = 1.6
ALL_SCENARIOS = ["N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08"]

CLIPS = {
    "n01_answer": "full_033_877.5s.wav",
    "n02_thinking": "full_015_344.9s.wav",
    "n03_um": "hesitant_040_101.6s.wav",
    "n03_rest": "hesitant_041_104.4s.wav",
    "bc_mm": "backchannel_084_688.8s.wav",
    "barge": "hesitant_092_878.5s.wav",
    "yeah_source": "hesitant_054_330.9s.wav",
    "rapid_1": "hesitant_039_87.8s.wav",
    "rapid_2": "hesitant_061_394.9s.wav",
    "rapid_3": "hesitant_054_330.9s.wav",
}
PROMPTERS = ["full_015_344.9s.wav", "hesitant_048_200.2s.wav", "hesitant_080_666.1s.wav"]
RESUME_GUARD_AGE_S = 3600
N02_INSERT_AT_S = 1.86
N02_SILENCE_S = 2.0
N03_GAP_S = 1.5
BACKCHANNEL_AT_S = 1.5
BARGE_AT_S = 2.0
SILENCE_WATCH_S = 18.0
RAPID_QUIET_S = 0.7

BUN_SCRIPT = """import { smallTalkInstruction } from '%(root)s/src/lib/instructions';
import { partnerById } from '%(root)s/src/lib/partners';
const partner = partnerById(process.argv[2]);
const instruction = smallTalkInstruction('', [], partner, [], null, '', null);
await Bun.write(process.argv[3], JSON.stringify({ instruction, voice: partner.voice, id: partner.id }));
"""


def find_clip(clips_dir: Path, name: str) -> Path:
    """클립 이름은 `kind_번호_시각.wav`다. 번호 앞부분만 맞으면 찾는다(예: back_084)."""
    exact = clips_dir / name
    if exact.exists():
        return exact
    prefix = "_".join(name.split("_")[:2])
    for path in sorted(clips_dir.glob(prefix + "_*.wav")):
        return path
    raise FileNotFoundError(f"클립 없음: {name}")


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path)) as w:
        if w.getframerate() != SR or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError(f"{path.name}: 16 kHz 모노 16비트가 아님")
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).copy()


class Utterance:
    def __init__(self, pcm: np.ndarray, label: str, source: str):
        self.pcm = pcm.astype(np.int16)
        self.label = label
        self.source = source
        bounds = M.speech_bounds(M.frame_db(self.pcm, SR))
        self.speech_start, self.speech_end = bounds if bounds else (0.0, len(self.pcm) / SR)

    @property
    def duration(self) -> float:
        return len(self.pcm) / SR


def clip_utterance(clips_dir: Path, name: str) -> Utterance:
    path = find_clip(clips_dir, name)
    return Utterance(read_wav(path), path.name, "학습자 실제 목소리 클립")


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(round(seconds * SR)), dtype=np.int16)


def with_inserted_silence(utt: Utterance, at_s: float, seconds: float) -> Utterance:
    cut = int(round(at_s * SR))
    pcm = np.concatenate([utt.pcm[:cut], silence(seconds), utt.pcm[cut:]])
    return Utterance(pcm, f"{utt.label} + {seconds:.1f}s 침묵@{at_s:.2f}s", utt.source)


def joined(parts, label: str, source: str) -> Utterance:
    return Utterance(np.concatenate(parts), label, source)


def yeah_utterance(clips_dir: Path) -> Utterance:
    """사용자 클립의 첫 낱말 'Yeah'만 잘라 쓴다. 길이가 맞지 않으면 macOS say로 합성하고 표시한다."""
    src = clip_utterance(clips_dir, CLIPS["yeah_source"])
    lead = M.leading_speech(M.frame_db(src.pcm, SR), gap_s=0.02, drop_db=25.0)
    if lead and 0.15 <= lead[1] - lead[0] <= 0.7:
        a, b = max(0, int(round((lead[0] - 0.05) * SR))), int(round((lead[1] + 0.03) * SR))
        return Utterance(src.pcm[a:b], f"{src.label}의 첫 낱말 {lead[0]:.2f}~{lead[1]:.2f}s", "학습자 실제 목소리 클립(첫 낱말만)")
    with tempfile.TemporaryDirectory() as tmp:
        aiff, wav = Path(tmp) / "y.aiff", Path(tmp) / "y.wav"
        subprocess.run(["say", "-v", "Samantha", "-o", str(aiff), "Yeah."], check=True)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(wav)], check=True)
        return Utterance(read_wav(wav), "say -v Samantha 'Yeah.'", "[합성] macOS say (맞는 실제 클립 없음)")


class MicTrack(MediaStreamTrack):
    kind = "audio"

    def __init__(self):
        super().__init__()
        self.queue = bytearray()
        self.sent = bytearray()
        self.frames = 0
        self.t0 = None

    async def recv(self):
        if self.t0 is None:
            self.t0 = time.monotonic()
        delay = self.t0 + self.frames * 0.02 - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        chunk = bytes(self.queue[: FRAME * 2])
        del self.queue[: FRAME * 2]
        chunk += b"\x00" * (FRAME * 2 - len(chunk))
        self.sent.extend(chunk)
        frame = AudioFrame(format="s16", layout="mono", samples=FRAME)
        frame.planes[0].update(chunk)
        frame.sample_rate = SR
        frame.pts = self.frames * FRAME
        frame.time_base = fractions.Fraction(1, SR)
        self.frames += 1
        return frame


class Call:
    """통화 한 건: 마이크로 클립을 시각표대로 내보내고 파트너 음성을 시각과 함께 모은다."""

    def __init__(self, url: str, request_data: dict):
        self.url = url
        self.request_data = request_data
        self.mic = MicTrack()
        self.pc = RTCPeerConnection()
        self.partner = bytearray()
        self.runs = []
        self.last_loud = None
        self.rtvi_events = []
        self.bot_texts = []

    def t(self) -> float:
        return 0.0 if self.mic.t0 is None else time.monotonic() - self.mic.t0

    async def connect(self) -> None:
        self.pc.addTrack(self.mic)
        channel = self.pc.createDataChannel("chat")

        @channel.on("open")
        def on_open():
            channel.send(json.dumps({"label": "rtvi-ai", "type": "client-ready", "id": "nat", "data": {"version": "1.0.0", "about": {"library": "naturalness_qa"}}}))

        @channel.on("message")
        def on_message(message):
            try:
                data = json.loads(message)
            except (TypeError, ValueError):
                return
            kind = data.get("type")
            if kind in ("bot-started-speaking", "bot-stopped-speaking", "user-started-speaking", "user-stopped-speaking", "bot-ready"):
                self.rtvi_events.append([round(self.t(), 3), kind])
            elif kind == "bot-output":
                text = (data.get("data") or {}).get("text", "")
                if text:
                    self.bot_texts.append([round(self.t(), 3), text])

        @self.pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                asyncio.ensure_future(self._consume(track))

        await self.pc.setLocalDescription(await self.pc.createOffer())
        body = {"sdp": self.pc.localDescription.sdp, "type": self.pc.localDescription.type, "request_data": self.request_data}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.url}/api/offer", json=body) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"/api/offer 실패 {resp.status}: {(await resp.text())[:300]}")
                answer = await resp.json()
        await self.pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
        deadline = time.monotonic() + 15
        while self.mic.t0 is None and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        if self.mic.t0 is None:
            raise RuntimeError("15초 안에 마이크 트랙이 시작되지 않음(연결 실패)")

    async def _consume(self, track) -> None:
        resampler = AudioResampler(format="s16", layout="mono", rate=SR)
        while True:
            try:
                frame = await track.recv()
            except Exception:
                return
            arrive = self.t()
            out = resampler.resample(frame)
            for piece in out if isinstance(out, list) else [out]:
                if piece is not None:
                    self._place(piece.to_ndarray().reshape(-1).astype(np.int16), arrive)

    def _place(self, samples: np.ndarray, arrive: float) -> None:
        cur = len(self.partner) // 2 / SR
        start = arrive - len(samples) / SR
        if start > cur + 0.06:
            self.partner.extend(b"\x00\x00" * int(round((start - cur) * SR)))
            cur = len(self.partner) // 2 / SR
        self.partner.extend(samples.tobytes())
        db = M.frame_db(samples, SR)
        for i, value in enumerate(db):
            if value > M.SPEECH_DB:
                begin, end = cur + i * M.FRAME_S, cur + (i + 1) * M.FRAME_S
                if self.runs and begin - self.runs[-1][1] <= 0.25:
                    self.runs[-1][1] = end
                else:
                    self.runs.append([begin, end])
                self.last_loud = end

    def play(self, utt: Utterance) -> dict:
        """지금 바로 클립을 내보내기 시작한다. 마이크 시계 기준 시각을 돌려준다."""
        start = self.mic.frames * 0.02 + len(self.mic.queue) / (SR * 2)
        self.mic.queue.extend(utt.pcm.tobytes())
        return {
            "label": utt.label,
            "source": utt.source,
            "start": round(start, 3),
            "speech_start": round(start + utt.speech_start, 3),
            "speech_end": round(start + utt.speech_end, 3),
            "end": round(start + utt.duration, 3),
        }

    async def wait_until(self, predicate, timeout: float):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = predicate()
            if value:
                return value
            await asyncio.sleep(0.05)
        return None

    def onset_since(self, since: float):
        for begin, end in self.runs:
            if begin >= since and end - begin >= 0.15:
                return begin
        return None

    async def wait_onset(self, since: float, timeout: float):
        return await self.wait_until(lambda: self.onset_since(since), timeout)

    async def wait_partner_quiet(self, since: float, quiet_s: float, timeout: float):
        """since 뒤에 파트너가 말을 시작했고 quiet_s 동안 조용해질 때까지 기다린다. 끝난 시각(마지막 소리)을 돌려준다."""
        started = await self.wait_onset(since, timeout)
        if started is None:
            return None
        return await self.wait_until(lambda: self.last_loud if self.t() - self.last_loud >= quiet_s else None, timeout)

    async def sleep_until(self, t: float) -> None:
        await asyncio.sleep(max(0.0, t - self.t()))

    async def finish(self) -> None:
        await self.pc.close()

    def learner_pcm(self) -> np.ndarray:
        return np.frombuffer(bytes(self.mic.sent), dtype=np.int16)

    def partner_pcm(self) -> np.ndarray:
        return np.frombuffer(bytes(self.partner), dtype=np.int16)

    def save_stereo(self, path: Path) -> float:
        left, right = self.learner_pcm(), self.partner_pcm()
        n = max(len(left), len(right))
        stereo = np.zeros((n, 2), dtype=np.int16)
        stereo[: len(left), 0] = left
        stereo[: len(right), 1] = right
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(stereo.tobytes())
        return n / SR


def metric(key, label, value, unit, threshold, ok, note="", info=False):
    """value가 None이면 잴 수 없었던 것이라 note의 이유와 함께 FAIL로 둔다."""
    if value is None:
        verdict = "FAIL"
    elif info:
        verdict = "INFO"
    else:
        verdict = "PASS" if ok else "FAIL"
    return {"key": key, "label": label, "value": value, "unit": unit, "threshold": threshold, "verdict": verdict, "note": note}


def gap_metric(key, label, gap_ms, threshold_key="gap_ms", note=""):
    low, high = M.THRESHOLDS[threshold_key]
    if gap_ms is None:
        return metric(key, label, None, "ms", f"{low}~{high} ms", False, "파트너가 학습자 말 뒤에 말하지 않음 " + note)
    extra = " (말 위로 시작)" if gap_ms < 0 else ""
    return metric(key, label, gap_ms, "ms", f"{low}~{high} ms", M.in_range(gap_ms, threshold_key), (note + extra).strip())


def turn_stat_metrics(turns):
    stats = M.partner_turn_stats(turns)
    median = stats["words_median"]
    rate = stats["question_rate"]
    lo, hi = M.THRESHOLDS["words_per_turn_median"]
    out = [
        metric("words_per_turn", "파트너 턴당 단어(중앙값, 전문)", median, "단어", f"{lo}~{hi}", M.in_range(median, "words_per_turn_median"),
               f"턴 {stats['turns']}개, 단어 {stats['words']}" if median is not None else "전문에 파트너 턴 없음"),
        metric("question_rate", "질문으로 끝난 턴 비율(전문)", rate, "비율", f"≤ {M.THRESHOLDS['question_rate'][1]}", M.in_range(rate, "question_rate"),
               f"Sesame 48턴 중 9턴(19%) 질문으로 끝남" if rate is not None else "전문에 파트너 턴 없음"),
    ]
    return out


def segs_of(call: Call):
    return M.speech_segments(M.frame_db(call.partner_pcm(), SR))


def spoken_between(texts, start: float, end: float) -> str:
    return "".join(t for ts, t in texts if start <= ts <= end).strip()


def ended_on_sentence(text: str) -> bool:
    return text.rstrip().endswith((".", "?", "!"))


def age_transcript(path: Path) -> None:
    """server/resume.py는 10분 안에 끝난 같은 친구 통화 전문을 다음 통화 지시문에 붙인다. 시나리오끼리 섞이지 않도록 읽은 전문의 수정 시각을 1시간 전으로 돌린다."""
    old = time.time() - RESUME_GUARD_AGE_S
    os.utime(path, (old, old))


async def preface(call: Call) -> dict:
    """파트너 첫 인사가 시작되고 끝나기까지 기다린다. 인사가 끝난 시각(마지막 소리)을 돌려준다."""
    end = await call.wait_partner_quiet(0.0, 1.0, GREETING_TIMEOUT_S)
    if end is None:
        raise RuntimeError(f"{GREETING_TIMEOUT_S:.0f}초 안에 파트너 인사가 끝나지 않음")
    return {"greeting_end": round(end, 3)}


async def run_n01(call, ctx):
    ev = await preface(call)
    ev["learner"] = call.play(ctx["utt"]["n01_answer"])
    await call.wait_partner_quiet(ev["learner"]["end"] - 1.0, TURN_END_QUIET_S, REPLY_TIMEOUT_S)
    return ev


def analyze_n01(ev, segs, turns, texts):
    gap = M.response_gap_ms(ev["learner"]["speech_end"], segs)
    return [gap_metric("gap_ms", "학습자 말 끝 → 파트너 첫 소리", gap)] + turn_stat_metrics(turns)


async def run_n02(call, ctx):
    ev = await preface(call)
    ev["learner"] = call.play(ctx["utt"]["n02_thinking"])
    base = ctx["utt"]["n02_base"]
    ev["pause"] = [round(ev["learner"]["start"] + N02_INSERT_AT_S - 0.12, 3), round(ev["learner"]["start"] + N02_INSERT_AT_S + N02_SILENCE_S + 0.12, 3)]
    ev["base_clip"] = base.label
    await call.wait_partner_quiet(ev["learner"]["end"] - 1.0, TURN_END_QUIET_S, REPLY_TIMEOUT_S)
    return ev


def analyze_n02(ev, segs, turns, texts):
    starts = M.pause_false_starts(ev["pause"][0], ev["pause"][1], segs)
    return [
        metric("false_starts", "침묵 구간(2.0 s) 안에서 파트너가 새로 말을 시작한 횟수", len(starts), "회", "0회", len(starts) == 0,
               f"시작 시각 {starts}" if starts else "끼어들지 않고 기다림"),
        gap_metric("gap_ms", "문장 끝 → 파트너 첫 소리", M.response_gap_ms(ev["learner"]["speech_end"], segs)),
    ]


async def run_n03(call, ctx):
    ev = await preface(call)
    ev["learner"] = call.play(ctx["utt"]["n03"])
    um = ctx["utt"]["n03_um"]
    ev["hesitation"] = [round(ev["learner"]["start"] + um.speech_end + 0.05, 3), round(ev["learner"]["start"] + um.duration + N03_GAP_S + ctx["utt"]["n03_rest"].speech_start - 0.05, 3)]
    await call.wait_partner_quiet(ev["learner"]["end"] - 1.0, TURN_END_QUIET_S, REPLY_TIMEOUT_S)
    return ev


def analyze_n03(ev, segs, turns, texts):
    starts = M.pause_false_starts(ev["hesitation"][0], ev["hesitation"][1], segs)
    return [
        metric("false_starts", "'um...' 뒤 망설임(1.5 s) 안에서 파트너가 말을 시작한 횟수", len(starts), "회", "0회", len(starts) == 0,
               f"시작 시각 {starts}" if starts else "끼어들지 않고 기다림"),
        gap_metric("gap_ms", "나머지 문장 끝 → 파트너 첫 소리", M.response_gap_ms(ev["learner"]["speech_end"], segs)),
    ]


async def run_prompted(call, ctx, delay_s: float, key: str):
    """파트너에게 긴 대답을 시키는 질문을 하고, 파트너 말이 시작된 지 delay_s 뒤에 두 번째 클립을 재생한다."""
    ev = await preface(call)
    ev["prompter"] = call.play(ctx["prompter"])
    onset = await call.wait_onset(ev["prompter"]["speech_end"] - 0.5, REPLY_TIMEOUT_S)
    if onset is None:
        raise RuntimeError("프롬프트 질문에 파트너가 답하지 않음")
    ev["partner_onset"] = round(onset, 3)
    await call.sleep_until(onset + delay_s)
    ev[key] = call.play(ctx["utt"]["bc" if key == "backchannel" else "barge"])
    await call.wait_partner_quiet(ev[key]["end"] - 0.5, TURN_END_QUIET_S, REPLY_TIMEOUT_S + 15)
    return ev


async def run_n04(call, ctx):
    return await run_prompted(call, ctx, BACKCHANNEL_AT_S, "backchannel")


def analyze_n04(ev, segs, turns, texts):
    bc = ev["backchannel"]
    out = M.backchannel_outcome(segs, bc["speech_start"], bc["speech_end"])
    if out["status"] == "invalid":
        return [metric("bc_outcome", "맞장구 뒤 파트너 행동", None, "", "kept_going", False, "무효: 맞장구 시각에 파트너가 말하지 않음")]
    note = f"맞장구 {bc['speech_start']}~{bc['speech_end']} s, 파트너 첫 소리 {ev['partner_onset']} s"
    before = spoken_between(texts, ev["partner_onset"] - 0.3, bc["speech_start"] + 0.3)
    if out["status"] == "stopped":
        stop_t = bc["speech_start"] + out["stopped_after_s"]
        said_before = spoken_between(texts, ev["partner_onset"] - 0.3, stop_t + 0.3)
        after = spoken_between(texts, stop_t + 0.3, stop_t + 8.0)
        note += f"; {out['stopped_after_s']} s 뒤 멈춤, 다음 발화까지 {out['next_onset_s']} s; 멈추기 전 말: {said_before[-120:]!r}; 그 뒤 말: {after[:120]!r}"
        if ended_on_sentence(said_before):
            return [metric("bc_outcome", "맞장구 뒤 파트너 행동", None, "", "kept_going", False, "무효: 문장 끝에서 멈춰 자연 종료와 구분 불가. " + note)]
        label = "stopped_asked" if M.ends_with_question(after) else "stopped"
        return [metric("bc_outcome", "맞장구 뒤 파트너 행동", label, "", "kept_going", False, note)]
    note += f"; 말: {before[-100:]!r}"
    return [metric("bc_outcome", "맞장구 뒤 파트너 행동", "kept_going", "", "kept_going", True, note)]


async def run_n05(call, ctx):
    return await run_prompted(call, ctx, BARGE_AT_S, "barge_in")


def analyze_n05(ev, segs, turns, texts):
    b = ev["barge_in"]
    res = M.stop_latency(segs, b["speech_start"])
    if res["status"] == "not_speaking":
        return [metric("stop_latency_ms", "끼어든 뒤 파트너가 멈추기까지", None, "ms", "≤ 1000 ms", False, "무효: 끼어든 시각에 파트너가 말하지 않음")]
    if res["status"] == "no_stop":
        return [metric("stop_latency_ms", "끼어든 뒤 파트너가 멈추기까지", None, "ms", "≤ 1000 ms", False, "6 s 안에 멈추지 않음")]
    ms = int(round(res["latency_s"] * 1000))
    said_before = spoken_between(texts, ev["partner_onset"] - 0.3, res["segment"][1] + 0.3)
    detail = f"끼어듦 {b['speech_start']} s, 파트너 말 {res['segment'][0]}~{res['segment'][1]} s; 멈추기 전 말: {said_before[-120:]!r}"
    if ended_on_sentence(said_before):
        return [metric("stop_latency_ms", "끼어든 뒤 파트너가 멈추기까지", None, "ms", "≤ 1000 ms", False, "무효: 문장 끝에서 멈춰 자연 종료와 구분 불가. " + detail)]
    return [
        metric("stop_latency_ms", "끼어든 뒤 파트너가 멈추기까지", ms, "ms", "≤ 1000 ms", M.in_range(ms, "stop_latency_ms"), detail),
        gap_metric("reply_gap_ms", "끼어든 문장 끝 → 파트너 다음 발화", M.response_gap_ms(b["speech_end"], [s for s in segs if s[0] > res["segment"][1]])),
    ]


async def run_n06(call, ctx):
    ev = await preface(call)
    ev["silence_from"] = ev["greeting_end"]
    await call.sleep_until(ev["greeting_end"] + SILENCE_WATCH_S)
    return ev


def analyze_n06(ev, segs, turns, texts):
    seconds = M.reengage_seconds(segs, ev["greeting_end"], SILENCE_WATCH_S)
    greeting = next((t for who, t in turns if who == "Partner"), "")
    spoken = [t for ts, t in texts if ts > ev["greeting_end"] + 0.3]
    said = " ".join(spoken).strip()
    lo, hi = M.THRESHOLDS["reengage_s"]
    if seconds is None:
        reason = f"학습자 침묵 {SILENCE_WATCH_S:.0f} s 동안 파트너가 다시 말하지 않음"
        return [metric("reengage_s", "침묵 뒤 파트너가 다시 말을 꺼내기까지", None, "s", f"{lo}~{hi} s", False, reason),
                metric("reengage_text", "다시 꺼낸 말", None, "", "내용 있는 말", False, "재참여 없음")]
    return [
        metric("reengage_s", "침묵 뒤 파트너가 다시 말을 꺼내기까지", seconds, "s", f"{lo}~{hi} s", M.in_range(seconds, "reengage_s"),
               f"인사 끝 {ev['greeting_end']} s; 인사 질문 여부: {'예' if M.ends_with_question(greeting) else '아니오'}"),
        metric("reengage_text", "다시 꺼낸 말", said or None, "", "내용 있는 말(3단어 이상)", M.count_words(said) >= 3, "RTVI bot-output 글 기준" if said else "글을 받지 못함"),
    ]


async def run_n07(call, ctx):
    ev = await preface(call)
    ev["learner"] = call.play(ctx["utt"]["yeah"])
    await call.wait_partner_quiet(ev["learner"]["end"] - 0.5, TURN_END_QUIET_S, REPLY_TIMEOUT_S)
    return ev


def analyze_n07(ev, segs, turns, texts):
    reply = " ".join(t for ts, t in texts if ts > ev["learner"]["start"]).strip()
    gap = M.response_gap_ms(ev["learner"]["speech_end"], segs)
    words = M.statement_words(reply) if reply else None
    lo = M.THRESHOLDS["statement_words"][0]
    stats = M.partner_turn_stats(turns)
    return [
        metric("statement_words", "'Yeah'만 들은 뒤 파트너가 질문 아닌 문장으로 말한 단어", words, "단어", f"≥ {lo}", M.in_range(words, "statement_words"),
               f"답: {reply[:160]!r}; 질문으로 끝남: {'예' if M.ends_with_question(reply) else '아니오'}" if reply else "파트너 답 글을 받지 못함"),
        gap_metric("gap_ms", "'Yeah' 끝 → 파트너 첫 소리", gap, "gap_after_backchannel_ms"),
        metric("question_rate", "질문으로 끝난 턴 비율(전문)", stats["question_rate"], "비율", f"≤ {M.THRESHOLDS['question_rate'][1]}",
               M.in_range(stats["question_rate"], "question_rate"), f"턴 {stats['turns']}개", info=True),
    ]


async def run_n08(call, ctx):
    ev = await preface(call)
    ev["turns"] = []
    for key in ("rapid_1", "rapid_2", "rapid_3"):
        turn = call.play(ctx["utt"][key])
        ev["turns"].append(turn)
        end = await call.wait_partner_quiet(turn["end"] - 1.0, RAPID_QUIET_S if key != "rapid_3" else TURN_END_QUIET_S, REPLY_TIMEOUT_S)
        if end is None:
            ev["note"] = f"{key} 뒤 파트너 답이 없어 중단"
            break
    return ev


def analyze_n08(ev, segs, turns, texts):
    gaps = []
    for turn in ev["turns"]:
        gap = M.response_gap_ms(turn["speech_end"], [s for s in segs if s[0] > turn["speech_start"] - 0.05])
        gaps.append(gap)
    real = [g for g in gaps if g is not None]
    if len(real) < len(ev["turns"]) or len(real) < 3:
        return [metric("median_gap_ms", "3번 빠른 주고받기의 간격 중앙값", None, "ms", "600~2000 ms", False, f"파트너 답 {len(real)}/3회만 받음 {ev.get('note', '')}")]
    median = int(M.median_or_none(real))
    worst = max(real)
    return [
        metric("median_gap_ms", "3번 빠른 주고받기의 간격 중앙값", median, "ms", "600~2000 ms", M.in_range(median, "median_gap_ms"), f"간격 {gaps}"),
        metric("max_gap_ms", "가장 긴 간격", worst, "ms", "≤ 3000 ms", M.in_range(worst, "max_gap_ms")),
    ] + turn_stat_metrics(turns)


SCENARIOS = {
    "N01": ("정상 대답", run_n01, analyze_n01),
    "N02": ("생각하는 침묵(문장 중간 2.0 s)", run_n02, analyze_n02),
    "N03": ("망설임('um...' 뒤 나머지)", run_n03, analyze_n03),
    "N04": ("맞장구(파트너 턴 1.5 s 시점)", run_n04, analyze_n04),
    "N05": ("끼어들기(파트너 턴 2.0 s 시점)", run_n05, analyze_n05),
    "N06": ("긴 침묵(질문 뒤 10 s)", run_n06, analyze_n06),
    "N07": ("짧은 대답('Yeah'만)", run_n07, analyze_n07),
    "N08": ("빠른 주고받기(3번)", run_n08, analyze_n08),
}


def build_utterances(clips_dir: Path) -> dict:
    utt = {name: clip_utterance(clips_dir, clip) for name, clip in CLIPS.items() if name != "yeah_source"}
    utt["n02_base"] = utt["n02_thinking"]
    utt["n02_thinking"] = with_inserted_silence(utt["n02_base"], N02_INSERT_AT_S, N02_SILENCE_S)
    um, rest = utt["n03_um"], utt["n03_rest"]
    utt["n03"] = joined([um.pcm, silence(N03_GAP_S), rest.pcm], f"{um.label} + {N03_GAP_S:.1f}s 침묵 + {rest.label}", um.source)
    utt["bc"] = utt.pop("bc_mm")
    utt["yeah"] = yeah_utterance(clips_dir)
    return utt


def build_instruction(partner: str, instruction_file):
    if instruction_file:
        return Path(instruction_file).read_text(encoding="utf-8"), None
    with tempfile.TemporaryDirectory() as tmp:
        script, out = Path(tmp) / "gen.ts", Path(tmp) / "out.json"
        script.write_text(BUN_SCRIPT % {"root": str(ROOT)}, encoding="utf-8")
        subprocess.run(["bun", "run", str(script), partner, str(out)], check=True, cwd=ROOT)
        data = json.loads(out.read_text(encoding="utf-8"))
    return data["instruction"], data.get("voice")


def wait_for_transcript(directory: Path, since: float, timeout: float = 40.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = [p for p in directory.glob("*.md") if p.stat().st_mtime >= since]
        if found:
            return max(found, key=lambda p: p.stat().st_mtime)
        time.sleep(0.5)
    return None


async def run_scenario(sid: str, attempt: int, args, instruction: str, voice, utt: dict, wav_dir: Path) -> dict:
    title, run_fn, analyze_fn = SCENARIOS[sid]
    request = {"system_instruction": instruction, "mode": "smalltalk", "partner": args.partner}
    if voice:
        request["voice"] = voice
    if args.engine:
        request["engine"] = args.engine
    prompter = clip_utterance(Path(args.clips_dir), PROMPTERS[attempt % len(PROMPTERS)])
    result = {"id": sid, "title": title, "attempt": attempt + 1, "metrics": [], "valid": True}
    call = Call(args.url, request)
    since = time.time()
    try:
        await call.connect()
        ev = await run_fn(call, {"utt": utt, "prompter": prompter})
        result["events"] = ev
    except Exception as e:  # noqa: BLE001 - 시나리오 하나가 실패해도 나머지는 계속 잰다
        result["error"] = f"{type(e).__name__}: {e}"
        ev = None
    await asyncio.sleep(0.5)
    await call.finish()
    wav = wav_dir / f"{args.name}-{sid}.wav"
    result["wav"] = str(wav)
    result["wav_seconds"] = round(call.save_stereo(wav), 2)
    transcript = await asyncio.to_thread(wait_for_transcript, Path(args.transcript_dir).expanduser(), since)
    text = transcript.read_text(encoding="utf-8") if transcript else ""
    if transcript:
        age_transcript(transcript)
    turns = M.parse_transcript(text)
    result["transcript"] = str(transcript) if transcript else None
    result["turns"] = turns
    result["bot_texts"] = call.bot_texts
    result["rtvi_events"] = call.rtvi_events
    segs = segs_of(call)
    result["partner_segments"] = segs
    if ev is None:
        result["metrics"] = [metric("run", "시나리오 실행", None, "", "끝까지 실행", False, result.get("error", "알 수 없는 오류"))]
        result["valid"] = False
    else:
        result["metrics"] = analyze_fn(ev, segs, turns, call.bot_texts)
        result["valid"] = not any("무효" in m["note"] for m in result["metrics"])
    return result


def render_markdown(results, args, utt_sources) -> str:
    lines = [f"# 자연스러움 점수표: {args.name}", ""]
    lines += [
        f"- 엔진 표시: {args.engine or '(없음: 서버 기본 = Gemini Live)'}",
        f"- 파트너: {args.partner}",
        f"- 서버: {args.url}",
        f"- 실행 시각: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "- 시각 기준: 학습자 마이크 첫 프레임 = 0 s. 간격은 클라이언트 수신 기준이라 로컬 연결에서도 수신 버퍼가 들어 있다(스모크에서 RTVI bot-started-speaking보다 약 0.1 s 늦게 잡혔다).",
        "- 파트너 말 판정: 20 ms 프레임 에너지 > -50 dBFS, 0.3 s 이하 틈은 이어 붙임, 0.12 s 미만은 버림.",
        "", "## 요약 (시나리오 × 지표)", "", "| 시나리오 | 지표 | 값 | 기준 | 판정 |", "|---|---|---|---|---|",
    ]
    for r in results:
        for m in r["metrics"]:
            value = "(측정 불가)" if m["value"] is None else f"{m['value']} {m['unit']}".strip()
            if len(value) > 60:
                value = value[:57] + "..."
            lines.append(f"| {r['id']} {r['title']} | {m['label']} | {value} | {m['threshold']} | {m['verdict']} |")
    lines += ["", "## 시나리오별 상세", ""]
    for r in results:
        lines += [f"### {r['id']} {r['title']} (시도 {r['attempt']}회째, 무효 재시도 포함)", ""]
        if r.get("error"):
            lines.append(f"- 실행 오류: {r['error']}")
        for m in r["metrics"]:
            lines.append(f"- [{m['verdict']}] {m['label']}: {m['value']} {m['unit']} (기준 {m['threshold']}) {('— ' + m['note']) if m['note'] else ''}")
        for e in r.get("earlier_attempts", []):
            reasons = "; ".join(m["note"][:200] for m in e["metrics"] if m["note"]) or e.get("error") or ""
            lines.append(f"- 무효로 버린 {e['attempt']}번째 시도: {reasons}")
        lines.append(f"- 스테레오 WAV(왼쪽 학습자, 오른쪽 파트너): `{r['wav']}` ({r['wav_seconds']} s)")
        lines.append(f"- 전문: `{r['transcript']}`")
        for who, text in r.get("turns", [])[:8]:
            lines.append(f"  - {who}: {text[:200]}")
        lines.append("")
    lines += ["## 쓴 학습자 소리", ""]
    for name, (label, source) in utt_sources.items():
        lines.append(f"- {name}: {label} — {source}")
    return "\n".join(lines) + "\n"


async def main_async(args) -> int:
    clips_dir = Path(args.clips_dir)
    utt = build_utterances(clips_dir)
    instruction, voice = build_instruction(args.partner, args.instruction)
    voice = args.voice or voice
    out_dir = Path(args.out_dir)
    wav_dir = out_dir / "wavs"
    wanted = [s.strip().upper() for s in args.scenarios.split(",") if s.strip()]
    results = []
    for sid in wanted:
        earlier = []
        for attempt in range(args.retries + 1):
            print(f"[{sid}] 시도 {attempt + 1} ...", flush=True)
            result = await run_scenario(sid, attempt, args, instruction, voice, utt, wav_dir)
            verdicts = ", ".join(f"{m['key']}={m['verdict']}" for m in result["metrics"])
            print(f"[{sid}] {'유효' if result['valid'] else '무효'} {verdicts}  wav {result['wav_seconds']} s", flush=True)
            if result["valid"] or sid not in ("N04", "N05"):
                break
            earlier.append({"attempt": attempt + 1, "error": result.get("error"), "metrics": result["metrics"], "wav": result["wav"]})
        result["earlier_attempts"] = earlier
        results.append(result)
    utt_sources = {k: (u.label, u.source) for k, u in utt.items()}
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "name": args.name,
        "engine": args.engine,
        "partner": args.partner,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "thresholds": {k: list(v) for k, v in M.THRESHOLDS.items()},
        "utterances": {k: {"label": a, "source": b} for k, (a, b) in utt_sources.items()},
        "scenarios": results,
    }
    (out_dir / f"{args.name}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out_dir / f"{args.name}.md").write_text(render_markdown(results, args, utt_sources), encoding="utf-8")
    failed = sum(1 for r in results for m in r["metrics"] if m["verdict"] == "FAIL")
    print(f"점수표: {out_dir / (args.name + '.md')}  (FAIL 지표 {failed}개)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="english-tutor 대화 자연스러움 시험 (N01~N08)")
    parser.add_argument("--url", default="http://127.0.0.1:8981")
    parser.add_argument("--transcript-dir", required=True, help="서버가 통화 전문을 저장하는 TRANSCRIPT_DIR")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--name", default="baseline-gemini-live")
    parser.add_argument("--partner", default="jake")
    parser.add_argument("--engine", default=None, help="request_data.engine으로 그대로 넘긴다")
    parser.add_argument("--instruction", default=None, help="파트너 지시문 파일. 없으면 bun으로 smallTalkInstruction을 만든다")
    parser.add_argument("--voice", default=None)
    parser.add_argument("--clips-dir", default=DEFAULT_CLIPS_DIR)
    parser.add_argument("--scenarios", default=",".join(ALL_SCENARIOS))
    parser.add_argument("--retries", type=int, default=2, help="N04·N05가 무효(파트너가 그 시각에 말 안 함)일 때 다시 거는 횟수")
    args = parser.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

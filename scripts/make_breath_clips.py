#!/usr/bin/env python3
"""들숨 클립 만들기: Vertex Gemini 3.8 Flash TTS의 <breath> 태그로 목소리마다 들숨을 만들어 잘라 저장한다.

실행(저장소 루트에서, ADC 로그인 필요):
  .venv/bin/python scripts/make_breath_clips.py [--voices Kore,Leda] [--per-voice 7] [--cache /tmp/breath-gen]

- 파트너 목소리와 같은 prebuilt voice 이름으로 "Mm-hm. <breath> So what happened next?" 같은 문장을 만든다.
- 말 사이의 약한 무성 잡음 섬(들숨)만 잘라 내고, 말소리가 시작되기 직전(0.12초 안)의 것을 쓴다.
- 클립은 24000Hz 모노 16비트 WAV로 server/assets/breaths/<목소리>/bNN.wav 에 저장한다.
- 레벨: 클립의 평균 프레임 레벨이 "말소리 기준(NOMINAL_SPEECH_DB)" 보다 REL_DB 만큼 낮게 맞춘다.
  (Maya 실측: 말소리보다 27~49 dB 낮음, server/breath_insert.py가 실행 시 실제 말소리 크기에 맞춰 다시 조정한다.)
"""
import argparse
import hashlib
import os
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "server" / "assets" / "breaths"
SR = 24000
HOP = 0.01
MODEL = "gemini-3.8-flash-tts"
LOCATION = "global"
VOICES = ("Kore", "Leda", "Charon", "Iapetus", "Sulafat", "Fenrir", "Zephyr", "Achird")
CARRIERS = (
    "Mm-hm. <breath> So, what happened next?",
    "Right. <breath> Well, I think that makes sense.",
    "Okay. <breath> Tell me more about that.",
    "Yeah. <breath> Actually, I had something similar last week.",
    "Oh nice. <breath> And how was the food?",
    "Gotcha. <breath> So what are you going to do now?",
    "Hm. <breath> That sounds like a long day, honestly.",
    "Exactly. <breath> I mean, it depends on who you ask.",
    "Sure. <breath> Let me think about how to say that.",
    "Wow. <breath> And then what did your boss say?",
    "<breath> So, how did that go?",
    "<breath> Okay, here's what I think.",
    "<breath> Well, that's a good question.",
    "<breath> Honestly, I never thought about it that way.",
    "Yeah, totally. <breath> What I meant was, it's kind of complicated.",
    "Ha, nice. <breath> So where did you go after that?",
    "I see. <breath> That makes a lot of sense, actually.",
    "Okay, so. <breath> The first thing I did was call my sister.",
    "Right, right. <breath> And did it work out in the end?",
    "Oh, really? <breath> I did not know that.",
    "Cool. <breath> Let's talk about your weekend.",
    "Mm. <breath> I think you're right about that.",
    "Ah, okay. <breath> So what did you end up doing?",
    "Huh. <breath> I hadn't thought of it like that.",
    "Yeah, I get that. <breath> It's a lot to deal with.",
    "Nice. <breath> Where was that again?",
    "Okay. <breath> And what happened after the meeting?",
    "Really? <breath> Tell me what she said.",
    "Oh, wow. <breath> That sounds pretty stressful.",
    "Alright. <breath> Let me ask you something else.",
    "Mm-hm. <breath> Go on, I'm listening.",
    "Ha. <breath> Okay, that's fair.",
)
NOMINAL_SPEECH_DB = -20.0
REL_DB = -36.0
MIN_DUR, MAX_DUR = 0.20, 0.34  # 삽입이 늘리는 시간 상한 0.35초 안
FADE = 0.012
REL_RANGE = (-47.0, -28.0)
JUDGE_MODEL = "gemini-2.5-flash"
JUDGE_PROMPT = (
    "This audio clip is very short and quiet and was cut from a conversation. It is not speech. "
    "Is it a natural human in-breath (an audible inhale before speaking)? "
    "Reply exactly in this format: SOUND: <short description>; INBREATH: yes/no/unsure."
)


def frame_db(x):
    h = int(SR * HOP)
    n = len(x) // h
    return 10 * np.log10(np.mean(x[: n * h].reshape(n, h) ** 2, 1) + 1e-12)


def read_wav(data):
    import io

    with wave.open(io.BytesIO(data)) as w:
        sr, pcm = w.getframerate(), w.readframes(w.getnframes())
    x = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) / 32768
    if sr != SR:
        x = np.interp(np.arange(0, len(x), sr / SR), np.arange(len(x)), x)
    return x


def runs(mask):
    out, i = [], 0
    while i < len(mask):
        if mask[i]:
            j = i
            while j < len(mask) and mask[j]:
                j += 1
            out.append((i, j))
            i = j
        else:
            i += 1
    return out


def extract(x):
    """x(24k float)에서 말소리 시작 직전의 들숨 섬 하나를 (클립, 정보)로 돌려준다. 없으면 None."""
    db = frame_db(x)
    if len(db) < 30:
        return None
    loud = db[db > db.max() - 25]
    ref = float(np.percentile(loud, 90))
    speech = db > ref - 20
    sp = [(0, 0)] + [r for r in runs(speech) if r[1] - r[0] >= 5]
    best = None
    for (_, prev_end), (onset, _) in zip(sp, sp[1:]):
        if onset - prev_end < 25:
            continue
        quiet = float(np.percentile(db[prev_end:onset], 15))
        settled = np.where(db[prev_end:onset] <= quiet + 6)[0]
        if not len(settled):
            continue
        lo = prev_end + int(settled[0])
        mask = np.zeros(len(db), bool)
        mask[lo:onset] = (db[lo:onset] > quiet + 10) & (db[lo:onset] < ref - 22)
        for a, b in runs(mask):
            while b - a > 3 and db[a] > np.median(db[a:b]) + 10:  # 앞머리 클릭 제거
                a += 1
            while b - a > MAX_DUR / HOP and db[a] < db[b - 1]:  # 길면 약한 쪽 끝부터 줄인다
                a += 1
            while b - a > MAX_DUR / HOP:
                b -= 1
            dur = (b - a) * HOP
            rel = float(np.mean(db[a:b])) - ref
            if MIN_DUR <= dur and REL_RANGE[0] <= rel <= REL_RANGE[1] and (best is None or onset - b < best[3]):
                best = (a, b, onset, onset - b)
    if best is None:
        return None
    a, b, onset, _ = best
    dur = (b - a) * HOP
    seg = x[int(a * HOP * SR): int(b * HOP * SR)].copy()
    k = int(FADE * SR)
    ramp = np.linspace(0, 1, k)
    seg[:k] *= ramp
    seg[-k:] *= ramp[::-1]
    mean_db = float(np.mean(db[a:b]))
    seg *= 10 ** ((NOMINAL_SPEECH_DB + REL_DB - mean_db) / 20)
    return seg, dict(dur=dur, rel=mean_db - ref, gap_to_onset=(onset - b) * HOP, ref=ref)


def retry_429(call, tries=8):
    for attempt in range(tries):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - 429(할당량)만 기다렸다 다시 시도한다
            if "429" not in str(exc) or attempt == tries - 1:
                raise
            time.sleep(20 * (attempt + 1))


def generate(client, voice, text, cache):
    from google.genai import types

    key = hashlib.sha256(f"{MODEL}\n{voice}\n{text}".encode()).hexdigest()[:24]
    path = cache / f"{voice}-{key}.wav"
    if path.is_file():
        return path.read_bytes()
    cfg = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))
        ),
    )
    part = retry_429(lambda: client.models.generate_content(model=MODEL, contents=text, config=cfg)).candidates[0].content.parts[0]
    if "wav" not in (part.inline_data.mime_type or ""):
        raise RuntimeError(f"unexpected mime {part.inline_data.mime_type}")
    cache.mkdir(parents=True, exist_ok=True)
    path.write_bytes(part.inline_data.data)
    return part.inline_data.data


def wav_bytes(seg):
    import io

    pcm = (np.clip(seg, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def write_wav(path, seg):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes(seg))


def judge(client, seg):
    from google.genai import types

    reply = retry_429(
        lambda: client.models.generate_content(
            model=JUDGE_MODEL,
            contents=[types.Part.from_bytes(data=wav_bytes(seg), mime_type="audio/wav"), JUDGE_PROMPT],
        )
    )
    return "INBREATH: yes" in (reply.text or "").replace("*", "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--voices", default=",".join(VOICES))
    ap.add_argument("--per-voice", type=int, default=7)
    ap.add_argument("--cache", default="/tmp/breath-gen")
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--no-judge", action="store_true", help="Gemini 오디오 판정 없이 수치 규칙만으로 고른다")
    args = ap.parse_args()
    sys.path.insert(0, str(ROOT))
    from google import genai

    from server.config_utils import get_project_id

    client = genai.Client(vertexai=True, project=get_project_id(), location=LOCATION)
    judge_client = genai.Client(vertexai=True, project=get_project_id(), location="us-central1")
    cache, out = Path(args.cache), Path(args.out)
    from concurrent.futures import ThreadPoolExecutor

    def fetch(job):
        try:
            return generate(client, job[0], job[1], cache)
        except Exception as exc:  # noqa: BLE001 - 한 문장이 실패해도 나머지를 계속 만든다
            print(f"{job[0]}: generate failed ({exc})")
            return None

    for voice in args.voices.split(","):
        found = []
        with ThreadPoolExecutor(1) as pool:
            wavs = list(pool.map(fetch, [(voice, t) for t in CARRIERS]))
        for text, wav in zip(CARRIERS, wavs):
            if wav is None:
                continue
            got = extract(read_wav(wav))
            if got:
                found.append(got)
            else:
                print(f"{voice}: no breath island in {text!r}")
        found.sort(key=lambda g: abs(g[1]["dur"] - 0.28) + g[1]["gap_to_onset"])
        kept = 0
        for seg, info in found:
            if kept >= args.per_voice:
                break
            if not args.no_judge and not judge(judge_client, seg):
                print(f"{voice}: judged not an in-breath (dur={info['dur']:.2f}s rel={info['rel']:.1f}dB)")
                continue
            kept += 1
            write_wav(out / voice / f"b{kept:02d}.wav", seg)
            print(f"{voice} b{kept:02d}: dur={info['dur']:.2f}s rel={info['rel']:.1f}dB gap_to_onset={info['gap_to_onset']:.2f}s")
        if kept < args.per_voice:
            print(f"{voice}: only {kept} clips kept")


if __name__ == "__main__":
    main()

# 마이크 없이 통화 경로 전체를 확인한다(Vertex 몇 센트). aiortc 가짜 브라우저가 /api/offer로 연결해
# 녹음 음성(macOS say)을 보내고, 튜터 음성·RTVI 메시지를 받은 뒤 끊고, 서버가 남긴 전문·원음을 확인한다.
# 실제 기록을 더럽히지 않도록 서버는 TRANSCRIPT_DIR·AUDIO_DIR을 임시 폴더로 바꿔 띄운다.
import argparse
import asyncio
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
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

SPEECH = "Hi Ms. Park. I started my day with a coffee. Where are you based?"
INSTRUCTION = """You are Ms. Park, a friendly English coach. Speak first with one short greeting.
The user is an English learner trying to: "Smoke Test" (a short check call).
Answer the learner briefly in easy English."""


def make_speech_wav(path: Path, lead_silence_sec: float = 8.0) -> None:
    aiff = path.with_suffix(".aiff")
    raw = path.with_name(path.stem + "-raw.wav")
    subprocess.run(["say", "-o", str(aiff), SPEECH], check=True)
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@16000", "-c", "1", str(aiff), str(raw)], check=True)
    with wave.open(str(raw)) as src:
        speech = src.readframes(src.getnframes())
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * int(16000 * lead_silence_sec) + speech + b"\x00\x00" * 16000 * 20)


async def consume_audio(track, stats):
    while True:
        try:
            frame = await track.recv()
        except Exception:
            return
        samples = frame.to_ndarray()
        stats["frames"] += 1
        if np.abs(samples).max() > 500:
            stats["loud_frames"] += 1
            stats.setdefault("first_loud_at", time.time())


async def run(url: str, seconds: float, wav: Path, mode: str = "mission", engine: str = "") -> dict:
    stats = {"frames": 0, "loud_frames": 0, "messages": [], "t0": time.time()}
    pc = RTCPeerConnection()
    player = MediaPlayer(str(wav))
    pc.addTrack(player.audio)
    channel = pc.createDataChannel("chat")

    @channel.on("open")
    def on_open():
        channel.send(json.dumps({"label": "rtvi-ai", "type": "client-ready", "id": "smoke",
                                 "data": {"version": "1.0.0", "about": {"library": "call_smoke"}}}))

    @channel.on("message")
    def on_message(message):
        try:
            data = json.loads(message)
        except (TypeError, ValueError):
            return
        stats["messages"].append(data.get("type"))
        stats.setdefault("first_at", {}).setdefault(data.get("type"), round(time.time() - stats["t0"], 1))
        if data.get("type") == "bot-output":
            stats.setdefault("bot_text", []).append(data.get("data", {}).get("text", ""))

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            asyncio.ensure_future(consume_audio(track, stats))

    await pc.setLocalDescription(await pc.createOffer())
    body = {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type,
            "request_data": {"system_instruction": INSTRUCTION, "mode": mode, **({"engine": engine} if engine else {})}}
    started = time.time()
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{url}/api/offer", json=body) as resp:
            if resp.status != 200:
                raise SystemExit(f"/api/offer 실패 {resp.status}: {await resp.text()}")
            answer = await resp.json()
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
    await asyncio.sleep(seconds)
    await pc.close()
    if "first_loud_at" in stats:
        stats["first_bot_audio_sec"] = round(stats.pop("first_loud_at") - started, 1)
    return stats


def wait_for_transcript(directory: Path, since: float, timeout: float = 30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = [p for p in directory.glob("*.md") if p.stat().st_mtime >= since]
        if found:
            return max(found, key=lambda p: p.stat().st_mtime)
        time.sleep(0.5)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="english-tutor 통화 경로 연결 시험")
    parser.add_argument("--url", default="http://127.0.0.1:8931")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--transcript-dir", default=os.getenv("TRANSCRIPT_DIR"), required=os.getenv("TRANSCRIPT_DIR") is None)
    parser.add_argument("--audio-dir", default=os.getenv("AUDIO_DIR"))
    parser.add_argument("--mode", default="mission", choices=["mission", "freetalk", "teachback", "smalltalk"])
    parser.add_argument("--engine", default="", help="request_data.engine (비우면 필드를 보내지 않아 기본 엔진)")
    args = parser.parse_args()

    work = Path(tempfile.mkdtemp(prefix="call-smoke-"))
    wav = work / "speech.wav"
    make_speech_wav(wav)
    since = time.time()
    stats = asyncio.run(run(args.url, args.seconds, wav, args.mode, args.engine))
    transcript = wait_for_transcript(Path(args.transcript_dir).expanduser(), since)
    audio = sorted(Path(args.audio_dir).expanduser().glob("*.wav")) if args.audio_dir else []

    loud_sec = stats["loud_frames"] * 0.02
    print(f"튜터 음성: 프레임 {stats['frames']}개, 소리 있는 구간 약 {loud_sec:.1f}초, 첫 소리 {stats.get('first_bot_audio_sec')}초")
    print(f"RTVI 메시지 종류: {sorted(set(t for t in stats['messages'] if t))}")
    print(f"메시지별 첫 도착(초): { {k: v for k, v in stats.get('first_at', {}).items() if k and ('speaking' in k or k in ('bot-ready', 'user-transcription'))} }")
    print(f"튜터 말(일부): {' '.join(stats.get('bot_text', []))[:200]!r}")
    print(f"전문: {transcript}")
    if transcript:
        print(transcript.read_text(encoding="utf-8")[:800])
    print(f"원음 WAV: {[p.name for p in audio]}")
    text = transcript.read_text(encoding="utf-8") if transcript else ""
    ok = loud_sec > 1.0 and transcript is not None and "Smoke Test" in text and (not args.engine or "**Partner:**" in text)
    print("SMOKE OK" if ok else "SMOKE FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

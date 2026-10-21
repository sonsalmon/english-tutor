# RNNoise 잡음 제거 필터 측정(네트워크·마이크 없음).
#
# macOS `say -v Samantha`로 중립 문장을 만들고, 합성 잡음(키보드 소리·숨소리 비슷한 필터 잡음·
# 선풍기 웅웅+핑크 잡음)을 몇 가지 SNR로 섞은 뒤, pipecat이 쓰는 RNNoiseFilter(16 kHz)에 20 ms씩 흘려
# 잡음만 있는 구간의 RMS 변화(dB)와 말 구간의 레벨 변화(dB)를 표로 찍는다.
#
# 구성: [잡음만 1.5초] [말] [잡음만 1.5초]. 잡음만 구간은 앞 0.5초(필터 적응)를 빼고 잰다.
# 말 구간 변화는 "섞은 말(잡음 포함)"과 "잡음 없는 말"을 각각 필터에 통과시켜 따로 적는다.
#
# 실행: 저장소 루트에서
#   /Users/sonsalmom/dev/english-tutor/.venv/bin/python scripts/noise_filter_check.py

import asyncio
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipecat.audio.filters.rnnoise_filter import RNNoiseFilter  # noqa: E402

SR = 16_000
CHUNK = SR // 50  # 20 ms
LEAD_S = 1.5
TAIL_S = 1.5
SKIP_S = 0.5  # 잡음만 구간에서 필터가 적응하는 앞부분은 재지 않는다
SENTENCES = [
    "The meeting starts at three o'clock in the main conference room.",
    "I usually take the train to work and read a book on the way.",
    "Could you send me the report by the end of the week?",
]
SNRS_DB = (20, 10, 5)


def make_speech(tmp: Path) -> np.ndarray:
    parts = []
    for i, text in enumerate(SENTENCES):
        path = tmp / f"s{i}.wav"
        subprocess.run(
            ["say", "-v", "Samantha", "--file-format=WAVE", "--data-format=LEI16@16000", "-o", str(path), text],
            check=True,
        )
        with wave.open(str(path), "rb") as w:
            assert w.getframerate() == SR and w.getnchannels() == 1
            parts.append(np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float64))
        parts.append(np.zeros(int(0.3 * SR)))
    return np.concatenate(parts)


def band_noise(n: int, lo: float, hi: float, rng) -> np.ndarray:
    spec = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    spec[(freqs < lo) | (freqs > hi)] = 0
    return np.fft.irfft(spec, n)


def pink_noise(n: int, rng) -> np.ndarray:
    spec = np.fft.rfft(rng.standard_normal(n))
    freqs = np.fft.rfftfreq(n, 1 / SR)
    freqs[0] = freqs[1]
    return np.fft.irfft(spec / np.sqrt(freqs), n)


def keyboard(n: int, rng) -> np.ndarray:
    out = np.zeros(n)
    click = int(0.012 * SR)
    env = np.exp(-np.arange(click) / (0.002 * SR))
    for t in rng.uniform(0, n - click, size=int(n / SR * 6)):  # 초당 약 6번 타건
        t = int(t)
        out[t : t + click] += rng.standard_normal(click) * env * rng.uniform(0.5, 1.0)
    return out


def breath(n: int, rng) -> np.ndarray:
    noise = band_noise(n, 200, 3000, rng)
    t = np.arange(n) / SR
    return noise * (0.5 + 0.5 * np.sin(2 * np.pi * 0.3 * t - np.pi / 2)) ** 2  # 약 3초 주기로 부풀었다 줄어드는 숨소리


def fan(n: int, rng) -> np.ndarray:
    t = np.arange(n) / SR
    hum = sum(np.sin(2 * np.pi * 120 * k * t) / k for k in (1, 2, 3, 4))
    return hum / np.std(hum) * 0.6 + pink_noise(n, rng) / np.std(pink_noise(n, rng)) * 0.8


NOISES = {"keyboard": keyboard, "breath": breath, "fan+pink": fan}


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


def db(a: float, b: float) -> float:
    return 20 * np.log10(max(a, 1e-9) / max(b, 1e-9))


async def run_filter(samples: np.ndarray) -> np.ndarray:
    f = RNNoiseFilter()
    await f.start(SR)
    pcm = np.clip(samples, -32768, 32767).astype(np.int16)
    pcm = np.concatenate([pcm, np.zeros(CHUNK * 10, dtype=np.int16)])  # 꼬리 지연 비우기
    out = []
    for i in range(0, len(pcm), CHUNK):
        out.append(np.frombuffer(await f.filter(pcm[i : i + CHUNK].tobytes()), dtype=np.int16))
    await f.stop()
    return np.concatenate(out).astype(np.float64)


def segments(speech_len: int):
    lead = (int(SKIP_S * SR), int(LEAD_S * SR))
    s0 = int(LEAD_S * SR)
    speech = (s0, s0 + speech_len)
    tail_start = s0 + speech_len
    tail = (tail_start + int(SKIP_S * SR), tail_start + int(TAIL_S * SR))
    return lead, speech, tail


async def main() -> None:
    rng = np.random.default_rng(7)
    with tempfile.TemporaryDirectory(prefix="noise-check-") as td:
        speech = make_speech(Path(td))
    speech = speech / rms(speech) * 3000.0
    lead_n, tail_n = int(LEAD_S * SR), int(TAIL_S * SR)
    total = lead_n + len(speech) + tail_n
    lead_seg, speech_seg, tail_seg = segments(len(speech))

    clean = np.concatenate([np.zeros(lead_n), speech, np.zeros(tail_n)])
    clean_out = await run_filter(clean)
    clean_change = db(rms(clean_out[slice(*speech_seg)]), rms(clean[slice(*speech_seg)]))
    print(f"깨끗한 말만 통과: 말 구간 레벨 변화 {clean_change:+.1f} dB (말 RMS {rms(speech):.0f})\n")

    header = f"{'noise':<10}{'SNR':>5}{'noise-only before':>19}{'after':>9}{'Δ dB':>8}{'speech Δ dB':>13}"
    print(header)
    print("-" * len(header))
    for name, maker in NOISES.items():
        base = maker(total, rng)
        base = base / rms(base[speech_seg[0] : speech_seg[1]] if name != "keyboard" else base)
        for snr in SNRS_DB:
            noise = base * rms(speech) / (10 ** (snr / 20))
            mixed = clean + noise
            out = await run_filter(mixed)
            n = min(len(out), len(mixed))
            noise_before = np.concatenate([mixed[slice(*lead_seg)], mixed[slice(*tail_seg)]])
            noise_after = np.concatenate([out[slice(*lead_seg)], out[slice(*tail_seg)]])
            sp_change = db(rms(out[slice(*speech_seg)][: n]), rms(mixed[slice(*speech_seg)]))
            nb, na = rms(noise_before), rms(noise_after)
            print(f"{name:<10}{snr:>4}d{nb:>19.1f}{na:>9.1f}{db(na, nb):>+8.1f}{sp_change:>+13.1f}")
    print("\n(RMS는 int16 단위. Δ dB가 음수일수록 잡음이 줄었고, speech Δ dB가 0에 가까울수록 말이 덜 뭉개졌다.)")


if __name__ == "__main__":
    asyncio.run(main())

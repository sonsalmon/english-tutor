// 응답 속도(학습자가 말을 끝낸 뒤 Ms. Park이 소리를 내기까지)를 브라우저에서 잰다.
// 서버 내부와 무관하게 마이크 트랙과 원격(봇) 오디오 트랙의 소리 크기(RMS)만 본다.

export type LatencyResult = { turns_ms: number[]; first_audio_ms: number | null };
export type CallLatency = { median_ms: number | null; p90_ms: number | null; turns: number; first_audio_ms: number | null };

const MIC_MIN = 0.02; // 마이크 문턱의 절대 하한
const BOT_MIN = 0.01; // 봇 소리 문턱의 절대 하한
const FLOOR_FACTOR = 3; // 문턱 = max(하한, 배경 소음 * 3)
const SPEECH_MS = 250; // 이만큼 이어서 문턱을 넘으면 학습자 발화
const DIP_MS = 60; // 이보다 짧게 끊기는 틈은 같은 발화로 본다
const END_MS = 200; // 이만큼 문턱 아래면 발화 끝(기록 시각은 떨어진 순간)
const BOT_RUN = 3; // 봇 소리는 연속 3샘플(60ms) 넘어야 시작으로 본다
const BOT_HOLD_MS = 100; // 봇 소리가 이만큼 조용해야 멈춘 것으로 본다
const MAX_MS = 10000;
const SAMPLE_MS = 20;

type Phase = 'idle' | 'speaking' | 'waiting';

export class TurnDetector {
  readonly turns: number[] = [];
  firstBotT: number | null = null;
  private micFloor = 0;
  private botFloor = 0;
  private phase: Phase = 'idle';
  private aboveSince: number | null = null;
  private lastAbove = 0;
  private pendingEnd: number | null = null;
  private learnerEnd = 0;
  private botRun = 0;
  private botRunStart = 0;
  private botOn = false;
  private botLastLoud = 0;

  private static floor(prev: number, v: number): number {
    return prev === 0 ? v : prev * 0.97 + v * 0.03;
  }

  /** 20ms마다 (시각 ms, 마이크 RMS, 봇 RMS)를 넣는다. */
  push(t: number, mic: number, bot: number): void {
    const botThr = Math.max(BOT_MIN, this.botFloor * FLOOR_FACTOR);
    if (bot > botThr) {
      if (this.botRun === 0) this.botRunStart = t;
      this.botRun += 1;
      this.botLastLoud = t;
      if (!this.botOn && this.botRun >= BOT_RUN) {
        this.botOn = true;
        this.onBotOnset(this.botRunStart);
      }
    } else {
      this.botRun = 0;
      if (this.botOn && t - this.botLastLoud >= BOT_HOLD_MS) this.botOn = false;
      if (!this.botOn) this.botFloor = TurnDetector.floor(this.botFloor, bot);
    }

    // 에코 방지: 봇이 말하는 동안 마이크 에너지는 무시한다.
    if (this.botOn) {
      this.aboveSince = null;
      return;
    }

    const micThr = Math.max(MIC_MIN, this.micFloor * FLOOR_FACTOR);
    const above = mic > micThr;
    if (!above && this.phase !== 'speaking') this.micFloor = TurnDetector.floor(this.micFloor, mic);

    if (this.phase === 'speaking') {
      if (above) {
        this.pendingEnd = null;
      } else {
        if (this.pendingEnd === null) this.pendingEnd = t;
        if (t - this.pendingEnd >= END_MS) {
          this.learnerEnd = this.pendingEnd;
          this.pendingEnd = null;
          this.phase = 'waiting';
          this.aboveSince = null;
        }
      }
      return;
    }

    // idle / waiting: 새 발화 시작 판정 (waiting 중 다시 말하면 앞 턴은 버리고 새로 시작)
    if (above) {
      this.lastAbove = t;
      if (this.aboveSince === null) this.aboveSince = t;
      if (t - this.aboveSince >= SPEECH_MS) {
        this.phase = 'speaking';
        this.pendingEnd = null;
        this.aboveSince = null;
      }
    } else if (this.aboveSince !== null && t - this.lastAbove > DIP_MS) {
      this.aboveSince = null;
    }
    if (this.phase === 'waiting' && t - this.learnerEnd > MAX_MS) this.phase = 'idle';
  }

  private onBotOnset(t: number): void {
    if (this.firstBotT === null) this.firstBotT = t;
    if (this.phase === 'waiting') {
      const lat = t - this.learnerEnd;
      if (lat >= 0 && lat <= MAX_MS) this.turns.push(Math.round(lat));
    } else if (this.phase === 'speaking' && this.pendingEnd !== null) {
      // 발화가 막 끝난 뒤(200ms 확인 구간) 시작한 봇 소리: 떨어진 순간 기준
      const lat = t - this.pendingEnd;
      if (lat >= 0 && lat <= MAX_MS) this.turns.push(Math.round(lat));
    }
    // 학습자가 말하는 중에 봇이 시작했으면 겹침이라 버린다.
    this.phase = 'idle';
    this.pendingEnd = null;
    this.aboveSince = null;
  }

  /** 일시정지처럼 흐름이 끊길 때 진행 중이던 턴을 버린다. */
  interrupt(): void {
    this.phase = 'idle';
    this.pendingEnd = null;
    this.aboveSince = null;
    this.botRun = 0;
    this.botOn = false;
  }
}

export type Sample = { t: number; mic: number; bot: number };

/** 순수 함수: 샘플 열에서 턴 지연과 첫소리 시각을 뽑는다. origin은 통화 버튼을 누른 시각. */
export function detectTurns(samples: Sample[], origin = 0): LatencyResult {
  const d = new TurnDetector();
  for (const s of samples) d.push(s.t, s.mic, s.bot);
  return { turns_ms: [...d.turns], first_audio_ms: d.firstBotT === null ? null : Math.max(0, Math.round(d.firstBotT - origin)) };
}

function rms(analyser: AnalyserNode, buf: Float32Array<ArrayBuffer>): number {
  analyser.getFloatTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) sum += buf[i] * buf[i];
  return Math.sqrt(sum / buf.length);
}

/** 브라우저 측정기: 마이크·봇 트랙을 AnalyserNode로 20ms마다 읽는다. */
export class LatencyMeter {
  private ctx: AudioContext | null = null;
  private mic: AnalyserNode | null = null;
  private bot: AnalyserNode | null = null;
  private micTrack: MediaStreamTrack | null = null;
  private botTrack: MediaStreamTrack | null = null;
  private timer: number | null = null;
  private paused = false;
  private readonly detector = new TurnDetector();
  private readonly buf = new Float32Array(1024) as Float32Array<ArrayBuffer>;

  constructor(private readonly origin: number = performance.now()) {
    try {
      this.ctx = new AudioContext();
      void this.ctx.resume().catch(() => undefined);
      this.timer = window.setInterval(() => this.tick(), SAMPLE_MS);
    } catch {
      this.ctx = null; // 측정만 못 할 뿐 통화는 그대로 간다
    }
  }

  private analyser(track: MediaStreamTrack): AnalyserNode | null {
    if (!this.ctx) return null;
    const node = this.ctx.createAnalyser();
    node.fftSize = 1024;
    this.ctx.createMediaStreamSource(new MediaStream([track])).connect(node); // destination에는 잇지 않는다
    return node;
  }

  attachMic(track: MediaStreamTrack): void {
    if (this.micTrack === track) return;
    this.micTrack = track;
    this.mic = this.analyser(track);
  }

  attachBot(track: MediaStreamTrack): void {
    if (this.botTrack === track) return;
    this.botTrack = track;
    this.bot = this.analyser(track);
  }

  setPaused(paused: boolean): void {
    this.paused = paused;
    if (paused) this.detector.interrupt();
  }

  private tick(): void {
    if (this.paused || !this.bot) return;
    const mic = this.mic && this.micTrack?.enabled ? rms(this.mic, this.buf) : 0;
    this.detector.push(performance.now(), mic, rms(this.bot, this.buf));
  }

  /** 측정을 멈추고 결과를 돌려준다. */
  stop(): LatencyResult {
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
    void this.ctx?.close().catch(() => undefined);
    this.ctx = null;
    const first = this.detector.firstBotT;
    return { turns_ms: [...this.detector.turns], first_audio_ms: first === null ? null : Math.max(0, Math.round(first - this.origin)) };
  }
}

// 통화가 끝나면 useCall이 결과를 잠깐 맡겨 두고, App이 FinishedCall에 붙이며 바로 비운다(다음 통화는 시작 때도 비운다).
// Summary는 이 모듈이 아니라 FinishedCall.latency만 읽는다.
let pending: LatencyResult | null = null;

export function stashLatency(result: LatencyResult): void {
  pending = result.turns_ms.length || result.first_audio_ms !== null ? result : null;
}

export function takePendingLatency(): LatencyResult | null {
  const result = pending;
  pending = null;
  return result;
}

export function clearPendingLatency(): void {
  pending = null;
}

export function summarizeLatency(result: LatencyResult): CallLatency {
  const sorted = [...result.turns_ms].sort((a, b) => a - b);
  const n = sorted.length;
  return {
    median_ms: n ? Math.round(n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2) : null,
    p90_ms: n ? sorted[Math.ceil(0.9 * n) - 1] : null,
    turns: n,
    first_audio_ms: result.first_audio_ms,
  };
}

function seconds(ms: number): string {
  return (Math.round(ms / 100) / 10).toFixed(1);
}

/** 화면에 한 줄로. 값이 없으면 null(줄을 숨긴다). */
export function latencyText(latency: CallLatency | null | undefined): string | null {
  if (!latency) return null;
  const parts: string[] = [];
  if (latency.median_ms != null) {
    const slow = latency.p90_ms != null ? ` (느릴 때 ${seconds(latency.p90_ms)}초)` : '';
    parts.push(`보통 ${seconds(latency.median_ms)}초${slow}`);
  }
  const text = parts.length ? `응답 속도: ${parts[0]}` : '';
  const first = latency.first_audio_ms != null ? `첫소리 ${seconds(latency.first_audio_ms)}초` : '';
  if (text && first) return `${text} · ${first}`;
  if (text) return text;
  return first ? `응답 속도: ${first}` : null;
}

// 발음 진단: 서버 API 도우미와 마이크 녹음기(16 kHz 모노 16비트 WAV).
// 서버는 받아쓰기만 한다. 어떤 문장을 읽는 중인지는 서버가 모른다(블라인드).

export type PronItem = { id: string; text: string };
export type PronTest = { items: PronItem[]; contrasts: Record<string, string> };
export type PronMisheard = { target: string; heard_text: string };
export type PronDirection = {
  target: string;
  other: string;
  total: number;
  as_target: number;
  as_other: number;
  unclear: number;
};
export type PronContrast = {
  contrast: string;
  label: string;
  total: number;
  as_target: number;
  as_other: number;
  unclear: number;
  misheard: PronMisheard[];
  unclear_heard?: PronMisheard[];
  directions?: PronDirection[];
  tip: string;
};
export type PronResult = { date: string; created_at: string; contrasts: PronContrast[]; cost_usd?: number | null };
export type PronAnswer = { id: string; text: string };

// GET /api/learner-profile 의 pron 키. api.ts의 LearnerProfile 타입에는 아직 없어서 여기서 보강한다.
export type PronWorst = { target: string; other: string; as_other: number; unclear: number; total: number };
export type PronWeak = { label: string; as_other: number; unclear: number; total: number; worst?: PronWorst | null };
export type PronSummary = { date: string; weak: PronWeak[] };

export function pronSummaryOf(profile: unknown): PronSummary | null {
  const pron = (profile as { pron?: PronSummary | null } | null)?.pron;
  return pron && typeof pron === 'object' && Array.isArray(pron.weak) ? pron : null;
}

async function detail(res: Response, fallback: string): Promise<string> {
  try {
    const body = await res.json();
    if (body?.detail) return String(body.detail);
  } catch {
    // JSON이 아니면 기본 문구를 쓴다.
  }
  return fallback;
}

export async function getPronTest(signal?: AbortSignal): Promise<PronTest> {
  const res = await fetch('/api/pron/test', { signal });
  if (!res.ok) throw new Error(await detail(res, '진단 문장을 불러오지 못했어요.'));
  const data = await res.json();
  return {
    items: Array.isArray(data?.items) ? data.items : [],
    contrasts: data?.contrasts && typeof data.contrasts === 'object' ? data.contrasts : {},
  };
}

// 결과가 없으면 {"result": null}, 있으면 결과 객체 그대로 온다.
export async function getPronLatest(signal?: AbortSignal): Promise<PronResult | null> {
  const res = await fetch('/api/pron/latest', { signal });
  if (!res.ok) throw new Error(await detail(res, '지난 결과를 불러오지 못했어요.'));
  const data = await res.json();
  if (!data || 'result' in data || !Array.isArray(data.contrasts)) return null;
  return data as PronResult;
}

export async function transcribePron(wav: Blob, signal?: AbortSignal): Promise<string> {
  let res: Response;
  try {
    res = await fetch('/api/pron/transcribe', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav, signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e;
    throw new Error('서버에 연결하지 못했어요.');
  }
  if (!res.ok) throw new Error(await detail(res, '발음을 받아쓰지 못했어요. 잠시 후 다시 해 주세요.'));
  const data = await res.json();
  return String(data?.text ?? '').trim();
}

export async function finishPron(answers: PronAnswer[]): Promise<PronResult> {
  let res: Response;
  try {
    res = await fetch('/api/pron/finish', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ answers }),
    });
  } catch {
    throw new Error('서버에 연결하지 못했어요.');
  }
  if (!res.ok) throw new Error(await detail(res, '결과를 만들지 못했어요.'));
  return (await res.json()) as PronResult;
}

export const WAV_RATE = 16000;
const MAX_SECONDS = 30; // 서버 상한(2MB)은 약 60초. 그 안쪽에서 자동으로 멈춘다.

export type Recording = { blob: Blob; seconds: number; peak: number };
export type Recorder = {
  stop: () => Promise<Recording>;
  cancel: () => void;
};

export class MicError extends Error {
  constructor(
    readonly reason: 'denied' | 'missing' | 'unsupported' | 'failed',
    message: string,
  ) {
    super(message);
    this.name = 'MicError';
  }
}

// 입력 샘플률 -> 16 kHz. 줄일 때는 구간 평균(박스 필터)이라 높은 소리가 접히는 것을 줄인다.
export function resample(input: Float32Array, fromRate: number, toRate = WAV_RATE): Float32Array {
  if (fromRate === toRate) return input;
  const ratio = fromRate / toRate;
  const length = Math.floor(input.length / ratio);
  const out = new Float32Array(length);
  for (let i = 0; i < length; i++) {
    const start = i * ratio;
    const end = Math.min(input.length, (i + 1) * ratio);
    const first = Math.floor(start);
    const last = Math.max(first + 1, Math.ceil(end));
    let sum = 0;
    let count = 0;
    for (let j = first; j < last && j < input.length; j++) {
      sum += input[j];
      count++;
    }
    out[i] = count ? sum / count : 0;
  }
  return out;
}

// 16비트 PCM WAV (모노). 머리글 44바이트 + 데이터.
export function encodeWav(samples: Float32Array, rate = WAV_RATE): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const text = (offset: number, s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(offset + i, s.charCodeAt(i));
  };
  text(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buffer], { type: 'audio/wav' });
}

const WORKLET_SOURCE = `
class Tap extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Float32Array(2048); this.n = 0; }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      for (let i = 0; i < ch.length; i++) {
        this.buf[this.n++] = ch[i];
        if (this.n === this.buf.length) { this.port.postMessage(this.buf.slice()); this.n = 0; }
      }
    }
    return true;
  }
}
registerProcessor('pron-tap', Tap);
`;

async function openMic(): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new MicError('unsupported', '이 브라우저에서는 마이크를 쓸 수 없어요. 주소가 https이거나 localhost인지 확인해 주세요.');
  }
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1 } });
  } catch (e) {
    const name = e instanceof DOMException ? e.name : '';
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      throw new MicError('denied', '마이크 사용이 막혀 있어요. 브라우저 주소창의 마이크 설정에서 허용한 뒤 다시 눌러 주세요.');
    }
    if (name === 'NotFoundError' || name === 'OverconstrainedError') {
      throw new MicError('missing', '마이크를 찾지 못했어요. 마이크가 연결되어 있는지 확인해 주세요.');
    }
    throw new MicError('failed', '마이크를 켜지 못했어요. 다른 앱이 마이크를 쓰고 있는지 확인해 주세요.');
  }
}

// 마이크(또는 getUserMedia가 돌려주는 어떤 MediaStream이든)를 Web Audio로 받아 WAV로 만든다.
// onLevel: 0~1 소리 크기(미터용). onAutoStop: 최대 길이에 닿아 스스로 멈췄을 때.
export async function startRecorder(onLevel?: (level: number) => void, onAutoStop?: () => void): Promise<Recorder> {
  const stream = await openMic();
  let context: AudioContext | null = null;
  try {
    context = new AudioContext();
    await context.resume();
    const source = context.createMediaStreamSource(stream);
    const chunks: Float32Array[] = [];
    let frames = 0;
    let peak = 0;
    let done = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const take = (chunk: Float32Array) => {
      if (done) return;
      chunks.push(chunk);
      frames += chunk.length;
      let sum = 0;
      for (let i = 0; i < chunk.length; i++) {
        const v = Math.abs(chunk[i]);
        sum += v * v;
        if (v > peak) peak = v;
      }
      onLevel?.(Math.min(1, Math.sqrt(sum / chunk.length) * 4));
    };

    // 소리를 끝까지 흘려보내지 않도록 음소거한 출력에 이어 둔다(일부 브라우저는 출력이 없으면 처리를 멈춘다).
    const mute = context.createGain();
    mute.gain.value = 0;
    mute.connect(context.destination);
    let teardownNode: () => void;
    try {
      if (!context.audioWorklet) throw new Error('no worklet');
      const url = URL.createObjectURL(new Blob([WORKLET_SOURCE], { type: 'text/javascript' }));
      try {
        await context.audioWorklet.addModule(url);
      } finally {
        URL.revokeObjectURL(url);
      }
      const node = new AudioWorkletNode(context, 'pron-tap', { numberOfOutputs: 1, channelCount: 1 });
      node.port.onmessage = (e: MessageEvent<Float32Array>) => take(e.data);
      source.connect(node).connect(mute);
      teardownNode = () => {
        node.port.onmessage = null;
        node.disconnect();
      };
    } catch {
      const node = context.createScriptProcessor(2048, 1, 1);
      node.onaudioprocess = (e) => take(new Float32Array(e.inputBuffer.getChannelData(0)));
      source.connect(node);
      node.connect(mute);
      teardownNode = () => {
        node.onaudioprocess = null;
        node.disconnect();
      };
    }

    const rate = context.sampleRate;
    const ctx = context;
    const release = () => {
      done = true;
      clearTimeout(timer);
      teardownNode();
      source.disconnect();
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close().catch(() => {});
    };

    timer = setTimeout(() => onAutoStop?.(), MAX_SECONDS * 1000);

    return {
      stop: async () => {
        const all = new Float32Array(frames);
        let offset = 0;
        for (const c of chunks) {
          all.set(c, offset);
          offset += c.length;
        }
        release();
        const pcm = resample(all, rate);
        return { blob: encodeWav(pcm), seconds: pcm.length / WAV_RATE, peak };
      },
      cancel: release,
    };
  } catch (e) {
    stream.getTracks().forEach((t) => t.stop());
    void context?.close().catch(() => {});
    throw e instanceof MicError ? e : new MicError('failed', '녹음을 시작하지 못했어요. 페이지를 새로 고친 뒤 다시 해 주세요.');
  }
}

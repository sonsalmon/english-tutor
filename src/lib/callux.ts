export type MicState = 'ok' | 'quiet' | 'noisy';
export type CallNotice = { kind: 'thinking'; on: boolean } | { kind: 'mic_level'; state: MicState };

export const REPLAY_RATE = 0.75;
// 상대가 말을 멈췄다가 이 시간 안에 다시 말하면 같은 차례로 본다.
export const TURN_GAP_MS = 1500;
// 서버 알림이 소리보다 먼저 닿을 수 있어, 멈춤 알림 뒤에도 이만큼 더 녹음한다.
export const TAIL_MS = 400;
export const MIN_SEGMENT_MS = 250;
export const MAX_SEGMENTS = 20;
// 이만큼 녹음했는데 소리가 하나도 안 나오면 이 브라우저는 상대 소리를 녹음하지 못하는 것으로 본다.
export const EMPTY_TAKE_MS = 1500;

export function parseCallNotice(data: unknown): CallNotice | null {
  if (!data || typeof data !== 'object') return null;
  const d = data as Record<string, unknown>;
  if (d.type === 'thinking') return { kind: 'thinking', on: d.on !== false };
  if (d.type === 'mic_level' && (d.state === 'ok' || d.state === 'quiet' || d.state === 'noisy')) {
    return { kind: 'mic_level', state: d.state };
  }
  return null;
}

export function micNoticeText(state: MicState): string | null {
  if (state === 'quiet') return '목소리가 작게 들려요. 마이크에 조금 가까이 말해 보세요.';
  if (state === 'noisy') return '주변 소리가 커서 말이 안 들릴 수 있어요. 조용한 곳에서 해 보세요.';
  return null;
}

const MIME_CANDIDATES = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus'];

export function pickRecorderMime(isSupported: (type: string) => boolean): string | null {
  const found = MIME_CANDIDATES.find((type) => isSupported(type));
  return found ?? null;
}

export function recorderMime(): string | null {
  if (typeof MediaRecorder === 'undefined' || typeof MediaStream === 'undefined') return null;
  return pickRecorderMime((type) => MediaRecorder.isTypeSupported(type));
}

// 상대가 한 차례 말한 소리 조각들을 들고 있는다. 다음 차례의 첫 조각이 끝나기 전에는 이전 차례를 지우지 않는다.
export class TurnTape<T> {
  private segments: T[] = [];
  private lastStopAt: number | null = null;
  private fresh = false;

  begin(now: number): void {
    this.fresh = this.lastStopAt === null || now - this.lastStopAt >= TURN_GAP_MS;
  }

  finish(segment: T | null, now: number): void {
    this.lastStopAt = now;
    if (!segment) return;
    if (this.fresh) {
      this.segments = [];
      this.fresh = false;
    }
    this.segments.push(segment);
    if (this.segments.length > MAX_SEGMENTS) this.segments.shift();
  }

  clips(): T[] {
    return [...this.segments];
  }

  get ready(): boolean {
    return this.segments.length > 0;
  }

  clear(): void {
    this.segments = [];
    this.lastStopAt = null;
    this.fresh = false;
  }
}

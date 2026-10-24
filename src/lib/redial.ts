// 끊긴 통화를 알아채고 다시 거는 규칙. 시계·네트워크 없이 시험할 수 있게 값만 받아 판정한다.

export const SILENCE_DEAD_MS = 8000; // 오디오 패킷이 오가지 않은 채로 이만큼 지나면 끊긴 것으로 본다
export const FAILED_DEAD_MS = 3000; // 연결이 failed/closed로 이만큼 머물면 끊긴 것으로 본다
export const DISCONNECTED_DEAD_MS = 8000; // disconnected는 저절로 돌아오기도 하므로 더 기다린다
export const MAX_REDIALS = 3;
export const REDIAL_DELAYS_MS = [1000, 3000, 7000] as const;
export const ATTEMPT_TIMEOUT_MS = 25000; // 다시 건 연결이 이 안에 준비되지 않으면 실패로 센다
export const TELEMETRY_EVERY_MS = 5000;

export type DeadReason = 'failed' | 'disconnected' | 'silence';

export const RESUME_TURNS = 12;
export type ResumeTurn = { who: 'me' | 'partner'; text: string };

// 다시 걸 때 서버에 넘길 직전 대화(자막 기준). 자동 다시 걸기는 끊긴 뒤 1초 만에 나가서 서버가 직전 전문을 아직 저장하지 못했을 수 있다.
export function resumeTurns(lines: { who: 'me' | 'park'; text: string; share?: unknown }[], count = RESUME_TURNS): ResumeTurn[] {
  return lines
    .filter((line) => !line.share && line.text.trim())
    .slice(-count)
    .map((line) => ({ who: line.who === 'me' ? 'me' : 'partner', text: line.text.trim() }));
}

export type Health = {
  lastActiveAt: number;
  lastIn: number | null;
  lastOut: number | null;
  badKind: 'failed' | 'disconnected' | null;
  badSince: number;
};

export type HealthInput = {
  inPk: number | null;
  outPk: number | null;
  conn?: string;
  ice?: string;
};

export type HealthContext = { paused: boolean; visible: boolean };

export function newHealth(now: number): Health {
  return { lastActiveAt: now, lastIn: null, lastOut: null, badKind: null, badSince: now };
}

function badKindOf(input: HealthInput): Health['badKind'] {
  const states = [input.conn, input.ice];
  if (states.includes('failed') || states.includes('closed')) return 'failed';
  if (states.includes('disconnected')) return 'disconnected';
  return null;
}

// 누적 패킷 수가 늘거나(진행) 줄면(연결을 새로 만들어 0부터 다시 셈) 오디오가 오가는 것으로 본다.
function moved(prev: number | null, next: number | null): boolean {
  return prev !== null && next !== null && next !== prev;
}

export function judgeHealth(h: Health, input: HealthInput, now: number, ctx: HealthContext): { health: Health; dead: DeadReason | null } {
  const next: Health = {
    ...h,
    lastIn: input.inPk ?? h.lastIn,
    lastOut: input.outPk ?? h.lastOut,
  };
  if (!ctx.visible) {
    // 화면이 숨은 동안은 iOS가 페이지를 멈춰 둘 수 있다. 돌아온 뒤부터 다시 센다.
    return { health: { ...next, lastActiveAt: now, badKind: null, badSince: now }, dead: null };
  }
  if (moved(h.lastIn, input.inPk) || moved(h.lastOut, input.outPk)) next.lastActiveAt = now;
  if (ctx.paused) next.lastActiveAt = now;

  const kind = badKindOf(input);
  if (kind !== h.badKind) {
    next.badKind = kind;
    next.badSince = now;
  }
  if (kind === 'failed' && now - next.badSince >= FAILED_DEAD_MS) return { health: next, dead: 'failed' };
  if (kind === 'disconnected' && now - next.badSince >= DISCONNECTED_DEAD_MS) return { health: next, dead: 'disconnected' };
  if (now - next.lastActiveAt >= SILENCE_DEAD_MS) return { health: next, dead: 'silence' };
  return { health: next, dead: null };
}

// attempt는 1부터. 다시 걸 횟수를 다 썼으면 null.
export function redialDelayMs(attempt: number): number | null {
  if (!Number.isInteger(attempt) || attempt < 1 || attempt > MAX_REDIALS) return null;
  return REDIAL_DELAYS_MS[attempt - 1];
}

// 한 번이라도 연결된 통화가 서버의 종료 안내 없이 끊겼을 때만 다시 건다.
export function shouldRedial(c: { everLive: boolean; endReason: string | null }): boolean {
  return c.everLive && c.endReason === null;
}

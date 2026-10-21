import type { ClipLine } from './api';
import { lineEnd } from './playerMachine';

// 자막 조정의 순수 함수: 영상별 싱크 저장·계산, 줄 시각 밀기, 줄 안 진행 비율.

export const SYNC_KEY = 'et.player.sync.v1';
/** 싱크를 한 번에 옮기는 크기(ms). */
export const SYNC_STEP_MS = 100;
/** 싱크 한도(ms). 이보다 크게 어긋난 영상은 자막이 아니라 영상 쪽 문제로 본다. */
export const SYNC_MAX_MS = 5000;
/** 싱크를 기억하는 영상 수. 넘치면 가장 오래 안 만진 영상부터 잊는다. */
export const SYNC_MAX_VIDEOS = 200;

/** 영상 ID -> 싱크(ms). 양수는 자막을 늦춘다(자막이 소리보다 먼저 나올 때), 음수는 당긴다. 0인 영상은 담지 않는다. */
export type SyncMap = Record<string, number>;

export function clampSync(ms: number): number {
  if (!Number.isFinite(ms)) return 0;
  const stepped = Math.round(ms / SYNC_STEP_MS) * SYNC_STEP_MS;
  return Math.max(-SYNC_MAX_MS, Math.min(SYNC_MAX_MS, stepped)) + 0;
}

export function stepSync(ms: number, direction: -1 | 1): number {
  return clampSync(ms + direction * SYNC_STEP_MS);
}

export function formatSync(ms: number): string {
  const sec = (Math.abs(ms) / 1000).toFixed(1);
  if (ms > 0) return `+${sec}초`;
  if (ms < 0) return `-${sec}초`;
  return '0.0초';
}

// 저장된 값에서 쓸 수 있는 칸만 살린다(옛 버전이나 손댄 값에도 화면이 멈추지 않게).
export function parseSyncMap(raw: unknown): SyncMap {
  const map: SyncMap = {};
  if (typeof raw !== 'object' || raw === null || Array.isArray(raw)) return map;
  for (const [id, value] of Object.entries(raw as Record<string, unknown>)) {
    if (typeof value !== 'number') continue;
    const ms = clampSync(value);
    if (ms !== 0) map[id] = ms;
  }
  return map;
}

function readMap(storage: Pick<Storage, 'getItem'>): SyncMap {
  try {
    return parseSyncMap(JSON.parse(storage.getItem(SYNC_KEY) ?? 'null'));
  } catch {
    return {};
  }
}

export function loadSync(videoId: string, storage: Pick<Storage, 'getItem'> = localStorage): number {
  return readMap(storage)[videoId] ?? 0;
}

export function saveSync(videoId: string, ms: number, storage: Pick<Storage, 'getItem' | 'setItem'> = localStorage): void {
  const map = readMap(storage);
  delete map[videoId];
  const value = clampSync(ms);
  if (value !== 0) map[videoId] = value;
  const ids = Object.keys(map);
  for (const old of ids.slice(0, Math.max(0, ids.length - SYNC_MAX_VIDEOS))) delete map[old];
  try {
    storage.setItem(SYNC_KEY, JSON.stringify(map));
  } catch {
    /* storage unavailable: 이번 화면에서만 유지된다 */
  }
}

/** 모든 줄의 시작·끝을 offsetMs만큼 민다(0 밑으로는 내려가지 않는다). 0이면 같은 배열을 돌려줘 다시 계산하지 않게 한다. */
export function shiftLines(lines: ClipLine[], offsetMs: number): ClipLine[] {
  if (offsetMs === 0) return lines;
  const s = offsetMs / 1000;
  return lines.map((l) => ({ ...l, start: Math.max(0, l.start + s), end: Math.max(0, l.end + s) }));
}

/** 영어 자막 흐림/숨김에서 탭해 보인 줄 id. 다른 줄로 가면 잊어서, 그 줄로 돌아오면 다시 가려진다. */
export function keepRevealed(revealedId: number | null, currentId: number | null): number | null {
  return revealedId !== null && revealedId === currentId ? revealedId : null;
}

/** 지금 줄 안에서 영상이 어디쯤인지(0~1). 줄 끝은 재생기가 멈추는 시각과 같은 값을 쓴다. */
export function lineFill(line: ClipLine, time: number): number {
  return Math.min(1, Math.max(0, (time - line.start) / (lineEnd(line) - line.start)));
}

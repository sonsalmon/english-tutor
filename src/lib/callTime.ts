// 통화 시간 표시 규칙: 시간 제한이 있는 통화는 남은 시간을, 제한 없는 친구 통화는 지난 시간을 센다.
import type { TimeLimits } from './api';
import type { CallMode, EndReason } from './useCall';

// 친구 통화에서 이 간격마다 "N분 지났어요"를 한 번 보인다.
export const ELAPSED_NOTICE_SEC = 600;
export const NOTICE_SHOW_MS = 8000;

// 통화 모드별 제한 시간(초). null이면 제한이 없다(친구 통화).
export function timeLimitFor(mode: CallMode, limits: TimeLimits): number | null {
  if (mode === 'teachback') return limits.teachback;
  if (mode === 'smalltalk') return limits.smalltalk;
  return limits.call;
}

// 연결된 뒤 지난 초. 일시정지로 멈춰 있던 시간은 뺀다. 멈춰 있는 동안은 멈춘 시각에 고정한다.
export function elapsedSeconds(nowMs: number, liveAtMs: number | null, pausedTotalMs: number, pausedAtMs: number | null = null): number {
  if (liveAtMs === null) return 0;
  const end = pausedAtMs ?? nowMs;
  return Math.max(0, (end - liveAtMs - pausedTotalMs) / 1000);
}

// 알림을 보여야 하는 새 간격에 들어섰으면 { count, minutes }, 아니면 null.
// lastCount는 이미 알린 간격의 수다. 한꺼번에 여러 간격을 건너뛰어도 가장 최근 간격 하나만 알린다.
export function nextElapsedNotice(elapsedSec: number, lastCount: number, intervalSec: number = ELAPSED_NOTICE_SEC): { count: number; minutes: number } | null {
  const count = Math.floor(Math.max(0, elapsedSec) / intervalSec);
  if (count < 1 || count <= lastCount) return null;
  return { count, minutes: Math.round((count * intervalSec) / 60) };
}

export const elapsedNoticeText = (minutes: number): string => `${minutes}분 지났어요`;

// 친구 통화에서 연결이 저절로 끊기면(끊기·시간 초과·미션 완료가 아니면) 다시 걸지 묻는다.
export function shouldOfferRedial(mode: CallMode, reason: EndReason | null): boolean {
  return mode === 'smalltalk' && reason === 'dropped';
}

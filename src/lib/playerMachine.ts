import type { ClipLine } from './api';
import { indexOfId, lineIndexAt } from './clipLines';

// 줄 재생 상태 머신(T1: 재생·이동·일시정지만). 시각과 현재 시계를 이벤트로 받는 순수 함수라 타이머 없이 시험한다.

/** 줄 시작보다 이만큼 앞에서 재생해 첫 단어가 잘리지 않게 한다. */
export const START_LEAD_S = 0.12;
/** seekTo 직후 플레이어가 낡은 시각을 돌려줄 수 있는 동안(ms) 시각 판정을 건너뛴다. */
export const SEEK_GUARD_MS = 250;
/** getCurrentTime 폴링 주기(ms). */
export const POLL_MS = 80;

export type PlayerState = {
  lines: readonly ClipLine[];
  /** 지금 줄의 위치. 줄 정보가 없으면 -1. */
  index: number;
  /** 처음 열 때와 "다시"(줄 정보 없음)가 돌아갈 영상 시각. */
  startTime: number;
  /** 플레이어가 마지막으로 알린 재생 여부. */
  playing: boolean;
  /** 시트를 열면서 멈췄다면 닫을 때 다시 재생한다. */
  resumeAfterHold: boolean;
  /** 이 시계(ms) 전까지는 tick을 무시한다. */
  guardUntil: number;
};

export type PlayerEvent =
  | { type: 'ready'; now: number }
  | { type: 'lines'; lines: readonly ClipLine[]; atId: number | null }
  | { type: 'tick'; time: number; now: number }
  | { type: 'status'; playing: boolean }
  | { type: 'prev' | 'next' | 'replay'; now: number }
  | { type: 'jump'; index: number; now: number }
  | { type: 'toggle' }
  | { type: 'hold' }
  | { type: 'release' };

export type PlayerAction = { type: 'seek'; time: number } | { type: 'play' } | { type: 'pause' };

export type Step = { state: PlayerState; actions: PlayerAction[] };

export function initialState(startTime: number): PlayerState {
  return { lines: [], index: -1, startTime: Math.max(0, startTime), playing: false, resumeAfterHold: false, guardUntil: 0 };
}

function leadTime(time: number): number {
  return Math.max(0, time - START_LEAD_S);
}

function moveTo(state: PlayerState, index: number, time: number, now: number): Step {
  return {
    state: { ...state, index, resumeAfterHold: false, guardUntil: now + SEEK_GUARD_MS },
    actions: [{ type: 'seek', time: leadTime(time) }, { type: 'play' }],
  };
}

export function step(state: PlayerState, event: PlayerEvent): Step {
  const same: Step = { state, actions: [] };
  const { lines, index } = state;
  switch (event.type) {
    case 'ready':
      return {
        state: { ...state, guardUntil: event.now + SEEK_GUARD_MS },
        actions: [{ type: 'seek', time: leadTime(state.startTime) }, { type: 'play' }],
      };
    case 'lines': {
      const at = indexOfId(event.lines, event.atId);
      const next = at >= 0 ? at : event.lines.length ? Math.max(0, lineIndexAt(event.lines, state.startTime + START_LEAD_S)) : -1;
      return { state: { ...state, lines: event.lines, index: next }, actions: [] };
    }
    case 'tick': {
      if (!lines.length || event.now < state.guardUntil) return same;
      const at = Math.max(0, lineIndexAt(lines, event.time + START_LEAD_S));
      return at === index ? same : { state: { ...state, index: at }, actions: [] };
    }
    case 'status':
      return event.playing === state.playing ? same : { state: { ...state, playing: event.playing }, actions: [] };
    case 'prev':
    case 'next': {
      if (!lines.length) return same;
      const to = Math.min(lines.length - 1, Math.max(0, index + (event.type === 'next' ? 1 : -1)));
      return moveTo(state, to, lines[to].start, event.now);
    }
    case 'replay':
      return lines.length ? moveTo(state, Math.max(0, index), lines[Math.max(0, index)].start, event.now) : moveTo(state, index, state.startTime, event.now);
    case 'jump':
      return event.index >= 0 && event.index < lines.length ? moveTo(state, event.index, lines[event.index].start, event.now) : same;
    case 'toggle':
      return { state, actions: [{ type: state.playing ? 'pause' : 'play' }] };
    case 'hold':
      return state.playing ? { state: { ...state, resumeAfterHold: true }, actions: [{ type: 'pause' }] } : same;
    case 'release':
      return state.resumeAfterHold ? { state: { ...state, resumeAfterHold: false }, actions: [{ type: 'play' }] } : same;
  }
}

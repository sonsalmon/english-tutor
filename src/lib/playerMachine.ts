import type { ClipLine } from './api';
import { indexOfId, lineIndexAt } from './clipLines';

// 줄 재생 상태 머신(재생·이동·일시정지, 줄마다 멈춤, 반복, 속도). 시각과 현재 시계를 이벤트로 받는 순수 함수라 타이머 없이 시험한다.

/** 줄 시작보다 이만큼 앞에서 재생해 첫 단어가 잘리지 않게 한다. */
export const START_LEAD_S = 0.12;
/** 줄 끝이나 구간 끝(endTime)보다 이만큼 일찍 멈춘다(다음 줄 첫 소리가 새지 않게). */
export const END_LEAD_S = 0.05;
/** seekTo 직후 플레이어가 낡은 시각을 돌려줄 수 있는 동안(ms) 시각 판정을 건너뛴다. */
export const SEEK_GUARD_MS = 250;
/** getCurrentTime 폴링 주기(ms). */
export const POLL_MS = 80;
/** 반복할 때 줄 사이에 쉬는 시간(ms). */
export const REPEAT_GAP_MS = 650;
/** 반복 3번 모드의 횟수. */
export const REPEAT_TIMES = 3;
/** 끝 시각이 시작과 너무 가까운 줄도 이만큼은 틀어 끝 판정이 곧바로 나지 않게 한다. */
export const MIN_LINE_S = 0.3;

export type RepeatMode = 'off' | 'x3' | 'inf';
export type PlayerSettings = { rate: number; repeat: RepeatMode; autoPause: boolean };
export const DEFAULT_SETTINGS: PlayerSettings = { rate: 1, repeat: 'off', autoPause: false };

export type PlayerState = PlayerSettings & {
  lines: readonly ClipLine[];
  /** 지금 줄의 위치. 줄 정보가 없으면 -1. */
  index: number;
  /** 처음 열 때와 "다시"(줄 정보 없음)가 돌아갈 영상 시각. */
  startTime: number;
  /** 이 시각에서 자동으로 멈춘다(피드 카드의 한 장면). null이면 끝까지 재생한다. */
  endTime: number | null;
  /** endTime에서 멈춘 뒤 다시 이동하기 전까지 true. */
  ended: boolean;
  /** 플레이어가 마지막으로 알린 재생 여부. */
  playing: boolean;
  /** 시트를 열면서 멈췄다면 닫을 때 다시 재생한다. */
  resumeAfterHold: boolean;
  /** 이 시계(ms) 전까지는 tick을 무시한다. */
  guardUntil: number;
  /** 지금 줄을 몇 번째로 듣는지(1부터). 반복 3번이면 1/3, 2/3, 3/3. */
  pass: number;
  /** 줄 끝에서 멈춰 "이어서 재생"을 기다리는 중. */
  held: boolean;
  /** 반복 사이에 쉬는 중이면 이 시계(ms)에 다시 튼다. 쉬지 않으면 null. 시트가 열린 동안은 무한대. */
  gapUntil: number | null;
};

export type PlayerEvent =
  | { type: 'ready'; now: number }
  | { type: 'lines'; lines: readonly ClipLine[]; atId: number | null }
  | { type: 'tick'; time: number; now: number }
  | { type: 'status'; playing: boolean }
  | { type: 'prev' | 'next' | 'replay'; now: number }
  | { type: 'jump'; index: number; now: number }
  | { type: 'toggle'; now?: number }
  | { type: 'hold' }
  | { type: 'release' }
  | { type: 'rate'; rate: number }
  | { type: 'repeat'; repeat: RepeatMode }
  | { type: 'autoPause'; on: boolean };

export type PlayerAction = { type: 'seek'; time: number } | { type: 'play' } | { type: 'pause' } | { type: 'setRate'; rate: number };

export type Step = { state: PlayerState; actions: PlayerAction[] };

export function initialState(startTime: number, endTime: number | null = null, settings: PlayerSettings = DEFAULT_SETTINGS): PlayerState {
  return {
    ...settings,
    lines: [],
    index: -1,
    startTime: Math.max(0, startTime),
    endTime,
    ended: false,
    playing: false,
    resumeAfterHold: false,
    guardUntil: 0,
    pass: 1,
    held: false,
    gapUntil: null,
  };
}

function leadTime(time: number): number {
  return Math.max(0, time - START_LEAD_S);
}

/** 줄이 멈추는 시각: 끝 시각(너무 짧은 줄은 시작 + MIN_LINE_S). 멈춤 판정은 여기서 END_LEAD_S를 뺀 시각이다. */
export function lineEnd(line: ClipLine): number {
  return Math.max(line.end, line.start + MIN_LINE_S);
}

function moveTo(state: PlayerState, index: number, time: number, now: number, pass = 1): Step {
  return {
    state: { ...state, index, pass, held: false, gapUntil: null, ended: false, resumeAfterHold: false, guardUntil: now + SEEK_GUARD_MS },
    actions: [{ type: 'seek', time: leadTime(time) }, { type: 'play' }],
  };
}

// 줄 끝에 닿았을 때: 반복이 남았으면 쉬었다가 다시, 아니면 멈추고 "이어서 재생"을 기다린다.
function finishLine(state: PlayerState, now: number): Step {
  const again = state.repeat === 'inf' || (state.repeat === 'x3' && state.pass < REPEAT_TIMES);
  if (again) return { state: { ...state, pass: state.pass + 1, gapUntil: now + REPEAT_GAP_MS, guardUntil: 0 }, actions: [{ type: 'pause' }] };
  return { state: { ...state, held: true }, actions: [{ type: 'pause' }] };
}

// 멈춰 있는 줄(쉬는 중이거나 줄 끝 멈춤)에서 재생을 누르면: 쉬는 중이면 지금 다시, 줄 끝 멈춤이면 다음 줄(마지막이면 그 줄을 다시).
function resume(state: PlayerState, now: number): Step {
  const { lines, index } = state;
  if (state.gapUntil !== null) return moveTo(state, index, lines[index].start, now, state.pass);
  const to = index + 1 < lines.length ? index + 1 : index;
  return moveTo(state, to, lines[to].start, now);
}

export function step(state: PlayerState, event: PlayerEvent): Step {
  const same: Step = { state, actions: [] };
  const { lines, index } = state;
  switch (event.type) {
    case 'ready':
      return {
        state: { ...state, guardUntil: event.now + SEEK_GUARD_MS },
        actions: [
          ...(state.rate !== 1 ? [{ type: 'setRate', rate: state.rate } as const] : []),
          { type: 'seek', time: leadTime(state.startTime) },
          { type: 'play' },
        ],
      };
    case 'lines': {
      const at = indexOfId(event.lines, event.atId);
      const next = at >= 0 ? at : event.lines.length ? Math.max(0, lineIndexAt(event.lines, state.startTime + START_LEAD_S)) : -1;
      return { state: { ...state, lines: event.lines, index: next }, actions: [] };
    }
    case 'tick': {
      if (state.gapUntil !== null && lines.length && index >= 0) {
        return event.now >= state.gapUntil ? moveTo(state, index, lines[index].start, event.now, state.pass) : same;
      }
      if (event.now < state.guardUntil || state.held) return same;
      // 장면 끝(피드 카드)과 줄 끝은 같은 멈춤이다: 먼저 닿는 쪽에서 한 번만 멈춘다.
      if (state.endTime !== null && !state.ended && event.time >= state.endTime - END_LEAD_S) {
        return { state: { ...state, ended: true, resumeAfterHold: false, gapUntil: null }, actions: [{ type: 'pause' }] };
      }
      if (!lines.length || index < 0) return same;
      if (state.autoPause || state.repeat !== 'off') {
        // 줄을 연습하는 중에는 시각이 아니라 지금 줄을 기준으로 끝을 본다.
        return event.time >= lineEnd(lines[index]) - END_LEAD_S ? finishLine(state, event.now) : same;
      }
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
      if (lines.length && index >= 0 && (state.held || state.gapUntil !== null)) return resume(state, event.now ?? 0);
      return { state, actions: [{ type: state.playing ? 'pause' : 'play' }] };
    case 'hold':
      if (state.gapUntil !== null) return { state: { ...state, gapUntil: Number.POSITIVE_INFINITY }, actions: [] };
      return state.playing ? { state: { ...state, resumeAfterHold: true }, actions: [{ type: 'pause' }] } : same;
    case 'release':
      if (state.gapUntil === Number.POSITIVE_INFINITY) return { state: { ...state, gapUntil: 0 }, actions: [] };
      return state.resumeAfterHold ? { state: { ...state, resumeAfterHold: false }, actions: [{ type: 'play' }] } : same;
    case 'rate':
      return event.rate === state.rate ? same : { state: { ...state, rate: event.rate }, actions: [{ type: 'setRate', rate: event.rate }] };
    case 'repeat':
      // 쉬는 중에 바꾸면 쉬기를 멈추고 그 자리에서 "이어서 재생"을 기다린다.
      return event.repeat === state.repeat ? same : { state: { ...state, repeat: event.repeat, pass: 1, held: state.held || state.gapUntil !== null, gapUntil: null }, actions: [] };
    case 'autoPause':
      return event.on === state.autoPause ? same : { state: { ...state, autoPause: event.on }, actions: [] };
  }
}

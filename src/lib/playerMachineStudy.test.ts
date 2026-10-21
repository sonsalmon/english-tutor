import { describe, expect, test } from 'bun:test';
import type { ClipLine } from './api';
import {
  DEFAULT_SETTINGS,
  END_LEAD_S,
  initialState,
  lineEnd,
  MIN_LINE_S,
  REPEAT_GAP_MS,
  SEEK_GUARD_MS,
  START_LEAD_S,
  step,
  type PlayerEvent,
  type PlayerSettings,
  type PlayerState,
} from './playerMachine';

const lines: ClipLine[] = [
  { id: 1000, start: 1, end: 3, text: 'one' },
  { id: 4000, start: 4, end: 6, text: 'two' },
  { id: 7000, start: 7, end: 9, text: 'three' },
];

function run(state: PlayerState, ...events: PlayerEvent[]): PlayerState {
  return events.reduce((s, e) => step(s, e).state, state);
}

// index번째 줄을 재생 중이고 시각 판정 보호 시간은 이미 지난 상태.
function playing(index: number, settings: Partial<PlayerSettings> = {}): PlayerState {
  const base = run(initialState(lines[index].start, { ...DEFAULT_SETTINGS, ...settings }), { type: 'lines', lines, atId: lines[index].id });
  return { ...base, playing: true };
}

const END_OF_FIRST = 3 - END_LEAD_S;

describe('줄마다 멈춤', () => {
  test('줄 끝 - 0.05초 직전까지는 재생하고, 그 시각에 일시정지한다', () => {
    const s = playing(0, { autoPause: true });
    const before = step(s, { type: 'tick', time: END_OF_FIRST - 0.01, now: 0 });
    expect(before.state).toBe(s);
    expect(before.actions).toEqual([]);
    const at = step(s, { type: 'tick', time: END_OF_FIRST, now: 0 });
    expect(at.actions).toEqual([{ type: 'pause' }]);
    expect(at.state.held).toBe(true);
    expect(at.state.index).toBe(0);
  });

  test('멈춘 뒤의 tick은 무시한다(다음 줄로 따라가지도 다시 멈추지도 않는다)', () => {
    const held = step(playing(0, { autoPause: true }), { type: 'tick', time: END_OF_FIRST, now: 0 }).state;
    const r = step(held, { type: 'tick', time: 4.5, now: 10_000 });
    expect(r.state).toBe(held);
    expect(r.actions).toEqual([]);
  });

  test('끄면 계속 재생하고 현재 줄은 시각을 따라간다', () => {
    const s = playing(0, { autoPause: false });
    const through = step(s, { type: 'tick', time: END_OF_FIRST, now: 0 });
    expect(through.actions).toEqual([]);
    expect(through.state.held).toBe(false);
    expect(step(s, { type: 'tick', time: 4, now: 0 }).state.index).toBe(1);
  });

  test('켜 둔 동안에는 다음 줄 시작이 가까워도 지금 줄이 그대로이고 끝에서만 멈춘다', () => {
    const s = playing(0, { autoPause: true });
    expect(step(s, { type: 'tick', time: 2, now: 0 }).state.index).toBe(0);
    expect(step(s, { type: 'tick', time: END_OF_FIRST, now: 0 }).state.index).toBe(0);
  });

  test('이동 직후 SEEK_GUARD_MS 안의 tick은 낡은 시각이라 끝 판정을 건너뛴다', () => {
    const moved = step(playing(0, { autoPause: true }), { type: 'next', now: 1000 }).state;
    const stale = step(moved, { type: 'tick', time: 2.99, now: 1000 + SEEK_GUARD_MS - 1 });
    expect(stale.state).toBe(moved);
    expect(stale.actions).toEqual([]);
    expect(step(moved, { type: 'tick', time: 5.95, now: 1000 + SEEK_GUARD_MS }).actions).toEqual([{ type: 'pause' }]);
  });

  test('줄 끝에서 재생(이어서)을 누르면 다음 줄 시작 0.12초 앞에서 재생한다', () => {
    const held = step(playing(0, { autoPause: true }), { type: 'tick', time: END_OF_FIRST, now: 0 }).state;
    const r = step(held, { type: 'toggle', now: 500 });
    expect(r.state.index).toBe(1);
    expect(r.state.held).toBe(false);
    expect(r.actions).toEqual([{ type: 'seek', time: 4 - START_LEAD_S }, { type: 'play' }]);
  });

  test('마지막 줄 끝에서 이어서 재생하면 그 줄을 다시 튼다', () => {
    const held = step(playing(2, { autoPause: true }), { type: 'tick', time: 9 - END_LEAD_S, now: 0 }).state;
    const r = step(held, { type: 'toggle', now: 0 });
    expect(r.state.index).toBe(2);
    expect(r.actions[0]).toEqual({ type: 'seek', time: 7 - START_LEAD_S });
  });

  test('끝이 시작과 거의 같은 줄도 MIN_LINE_S는 튼다', () => {
    const blip: ClipLine = { id: 5, start: 5, end: 5, text: 'x' };
    expect(lineEnd(blip)).toBe(5 + MIN_LINE_S);
    expect(lineEnd(lines[0])).toBe(3);
    const s = run(initialState(5, { ...DEFAULT_SETTINGS, autoPause: true }), { type: 'lines', lines: [blip], atId: 5 });
    expect(step(s, { type: 'tick', time: 5.2, now: 0 }).actions).toEqual([]);
    expect(step(s, { type: 'tick', time: 5 + MIN_LINE_S - END_LEAD_S, now: 0 }).actions).toEqual([{ type: 'pause' }]);
  });
});

describe('반복 3번', () => {
  const start = playing(0, { repeat: 'x3', autoPause: true });

  test('같은 줄을 3번 튼 뒤 멈추고, 사이에 650ms 쉰다. 칩 숫자는 1/3, 2/3, 3/3', () => {
    expect(start.pass).toBe(1);
    const first = step(start, { type: 'tick', time: END_OF_FIRST, now: 1000 });
    expect(first.actions).toEqual([{ type: 'pause' }]);
    expect(first.state.pass).toBe(2);
    expect(first.state.gapUntil).toBe(1000 + REPEAT_GAP_MS);
    expect(first.state.held).toBe(false);

    const waiting = step(first.state, { type: 'tick', time: END_OF_FIRST, now: 1000 + REPEAT_GAP_MS - 1 });
    expect(waiting.state).toBe(first.state);
    expect(waiting.actions).toEqual([]);

    const second = step(first.state, { type: 'tick', time: END_OF_FIRST, now: 1000 + REPEAT_GAP_MS });
    expect(second.actions).toEqual([{ type: 'seek', time: 1 - START_LEAD_S }, { type: 'play' }]);
    expect(second.state.pass).toBe(2);
    expect(second.state.gapUntil).toBeNull();
    expect(second.state.index).toBe(0);

    const afterSecond = step(second.state, { type: 'tick', time: END_OF_FIRST, now: 3000 });
    expect(afterSecond.state.pass).toBe(3);
    const third = step(afterSecond.state, { type: 'tick', time: END_OF_FIRST, now: 3000 + REPEAT_GAP_MS });
    expect(third.state.pass).toBe(3);

    const done = step(third.state, { type: 'tick', time: END_OF_FIRST, now: 6000 });
    expect(done.actions).toEqual([{ type: 'pause' }]);
    expect(done.state.held).toBe(true);
    expect(done.state.pass).toBe(3);
    expect(done.state.gapUntil).toBeNull();
  });

  test('줄마다 멈춤이 꺼져 있어도 3번 뒤에는 멈춘다', () => {
    let s = playing(0, { repeat: 'x3', autoPause: false });
    let now = 0;
    const reachEnd = () => {
      s = step(s, { type: 'tick', time: END_OF_FIRST, now }).state;
    };
    const replayAfterGap = () => {
      now += REPEAT_GAP_MS;
      s = step(s, { type: 'tick', time: END_OF_FIRST, now }).state;
      now += SEEK_GUARD_MS;
    };
    reachEnd();
    replayAfterGap();
    reachEnd();
    replayAfterGap();
    reachEnd();
    expect(s.held).toBe(true);
    expect(s.pass).toBe(3);
  });

  test('쉬는 중 재생을 누르면 지금 바로 그 줄을 다시 튼다(횟수는 그대로)', () => {
    const gap = step(start, { type: 'tick', time: END_OF_FIRST, now: 0 }).state;
    const r = step(gap, { type: 'toggle', now: 100 });
    expect(r.actions).toEqual([{ type: 'seek', time: 1 - START_LEAD_S }, { type: 'play' }]);
    expect(r.state.pass).toBe(2);
    expect(r.state.gapUntil).toBeNull();
  });

  test('쉬는 중 시트를 열면 쉬는 시간이 멈추고, 닫으면 곧바로 다시 튼다', () => {
    const gap = step(start, { type: 'tick', time: END_OF_FIRST, now: 0 }).state;
    const open = step(gap, { type: 'hold' }).state;
    expect(step(open, { type: 'tick', time: END_OF_FIRST, now: 999_999 }).actions).toEqual([]);
    const closed = step(open, { type: 'release' }).state;
    expect(step(closed, { type: 'tick', time: END_OF_FIRST, now: 1 }).actions).toEqual([{ type: 'seek', time: 1 - START_LEAD_S }, { type: 'play' }]);
  });

  test('이동, 다시, 줄 목록 탭은 횟수를 1로 되돌린다', () => {
    const second = step(start, { type: 'tick', time: END_OF_FIRST, now: 0 }).state;
    expect(second.pass).toBe(2);
    for (const e of [
      { type: 'next', now: 0 },
      { type: 'prev', now: 0 },
      { type: 'replay', now: 0 },
      { type: 'jump', index: 2, now: 0 },
    ] as const) {
      const r = step(second, e).state;
      expect(r.pass).toBe(1);
      expect(r.gapUntil).toBeNull();
      expect(r.held).toBe(false);
    }
  });
});

describe('반복 무한', () => {
  test('끝날 때마다 쉬었다 다시 틀고 횟수만 늘어난다', () => {
    let s = playing(1, { repeat: 'inf' });
    let now = 0;
    for (let i = 0; i < 6; i += 1) {
      const end = step(s, { type: 'tick', time: 6 - END_LEAD_S, now });
      expect(end.actions).toEqual([{ type: 'pause' }]);
      expect(end.state.held).toBe(false);
      now += REPEAT_GAP_MS;
      const again = step(end.state, { type: 'tick', time: 6, now });
      expect(again.actions[0]).toEqual({ type: 'seek', time: 4 - START_LEAD_S });
      s = again.state;
      now += SEEK_GUARD_MS;
    }
    expect(s.pass).toBe(7);
    expect(s.index).toBe(1);
  });
});

describe('설정 이벤트', () => {
  test('rate: 값이 바뀌면 setRate 동작, 같으면 아무 일도 없다', () => {
    const s = playing(0);
    const r = step(s, { type: 'rate', rate: 0.75 });
    expect(r.state.rate).toBe(0.75);
    expect(r.actions).toEqual([{ type: 'setRate', rate: 0.75 }]);
    expect(step(r.state, { type: 'rate', rate: 0.75 }).state).toBe(r.state);
  });

  test('ready: 속도가 1이 아니면 seek 앞에서 속도를 다시 적용하고, 1이면 적용하지 않는다', () => {
    const slow = step(initialState(4, { ...DEFAULT_SETTINGS, rate: 0.75 }), { type: 'ready', now: 0 });
    expect(slow.actions).toEqual([{ type: 'setRate', rate: 0.75 }, { type: 'seek', time: 4 - START_LEAD_S }, { type: 'play' }]);
    expect(step(initialState(4), { type: 'ready', now: 0 }).actions).toEqual([{ type: 'seek', time: 4 - START_LEAD_S }, { type: 'play' }]);
  });

  test('repeat: 바꾸면 횟수를 1로 되돌리고, 쉬는 중이었다면 그 자리에서 이어서 재생을 기다린다', () => {
    const gap = step(playing(0, { repeat: 'x3' }), { type: 'tick', time: END_OF_FIRST, now: 0 }).state;
    const r = step(gap, { type: 'repeat', repeat: 'off' }).state;
    expect(r.repeat).toBe('off');
    expect(r.pass).toBe(1);
    expect(r.gapUntil).toBeNull();
    expect(r.held).toBe(true);
    const s = playing(0);
    expect(step(s, { type: 'repeat', repeat: 'off' }).state).toBe(s);
  });

  test('autoPause: 바꾸면 반영하고 같으면 그대로 둔다', () => {
    const s = playing(0);
    expect(step(s, { type: 'autoPause', on: true }).state.autoPause).toBe(true);
    expect(step(s, { type: 'autoPause', on: false }).state).toBe(s);
  });

  test('입력 상태를 바꾸지 않는다', () => {
    const s = Object.freeze(playing(0, { repeat: 'x3', autoPause: true }));
    const events: PlayerEvent[] = [
      { type: 'tick', time: END_OF_FIRST, now: 1 },
      { type: 'toggle', now: 1 },
      { type: 'rate', rate: 1.5 },
      { type: 'repeat', repeat: 'inf' },
      { type: 'autoPause', on: false },
      { type: 'hold' },
      { type: 'release' },
    ];
    for (const e of events) expect(() => step(s, e)).not.toThrow();
  });
});

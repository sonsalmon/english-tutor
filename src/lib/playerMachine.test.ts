import { describe, expect, test } from 'bun:test';
import type { ClipLine } from './api';
import { initialState, SEEK_GUARD_MS, START_LEAD_S, step, type PlayerEvent, type PlayerState } from './playerMachine';

const lines: ClipLine[] = [
  { id: 1000, start: 1, end: 3, text: 'one' },
  { id: 4000, start: 4, end: 6, text: 'two' },
  { id: 7000, start: 7, end: 9, text: 'three' },
];

function run(state: PlayerState, ...events: PlayerEvent[]): PlayerState {
  return events.reduce((s, e) => step(s, e).state, state);
}

function withLines(index: number, extra: Partial<PlayerState> = {}): PlayerState {
  return { ...run(initialState(4), { type: 'lines', lines, atId: lines[index].id }), ...extra };
}

describe('ready', () => {
  test('시작 시각보다 0.12초 앞으로 가서 재생하고, 잠시 시각 판정을 건너뛴다', () => {
    const r = step(initialState(4), { type: 'ready', now: 1000 });
    expect(r.actions).toEqual([{ type: 'seek', time: 4 - START_LEAD_S }, { type: 'play' }]);
    expect(r.state.guardUntil).toBe(1000 + SEEK_GUARD_MS);
  });

  test('시작 시각이 0.12초보다 이르면 0으로 자른다', () => {
    expect(step(initialState(0.05), { type: 'ready', now: 0 }).actions[0]).toEqual({ type: 'seek', time: 0 });
  });
});

describe('lines', () => {
  test('atId 줄이 현재 줄이 된다', () => {
    expect(withLines(1).index).toBe(1);
  });

  test('atId가 없으면 시작 시각이 속한 줄, 줄이 없으면 -1', () => {
    expect(run(initialState(7), { type: 'lines', lines, atId: null }).index).toBe(2);
    expect(run(initialState(0), { type: 'lines', lines, atId: null }).index).toBe(0);
    expect(run(initialState(4), { type: 'lines', lines: [], atId: null }).index).toBe(-1);
  });
});

describe('다음 줄 / 이전 줄', () => {
  test('다음 줄: 그 줄 시작보다 0.12초 앞으로 가서 재생하고 현재 줄이 바뀐다', () => {
    const r = step(withLines(0), { type: 'next', now: 500 });
    expect(r.state.index).toBe(1);
    expect(r.actions).toEqual([{ type: 'seek', time: 4 - START_LEAD_S }, { type: 'play' }]);
    expect(r.state.guardUntil).toBe(500 + SEEK_GUARD_MS);
  });

  test('이전 줄은 앞 줄로, 첫 줄에서는 첫 줄을 다시 튼다', () => {
    const back = step(withLines(2), { type: 'prev', now: 0 });
    expect(back.state.index).toBe(1);
    expect(back.actions[0]).toEqual({ type: 'seek', time: 4 - START_LEAD_S });
    const first = step(withLines(0), { type: 'prev', now: 0 });
    expect(first.state.index).toBe(0);
    expect(first.actions[0]).toEqual({ type: 'seek', time: 1 - START_LEAD_S });
  });

  test('마지막 줄에서 다음 줄은 마지막 줄을 다시 튼다', () => {
    const r = step(withLines(2), { type: 'next', now: 0 });
    expect(r.state.index).toBe(2);
    expect(r.actions[0]).toEqual({ type: 'seek', time: 7 - START_LEAD_S });
  });

  test('줄 정보가 없으면 아무 일도 없다', () => {
    const s = initialState(4);
    for (const type of ['prev', 'next'] as const) {
      const r = step(s, { type, now: 0 });
      expect(r.state).toBe(s);
      expect(r.actions).toEqual([]);
    }
  });

  test('줄 시작이 0.12초보다 이르면 0으로 자른다', () => {
    const early: ClipLine[] = [
      { id: 50, start: 0.05, end: 2, text: 'a' },
      { id: 3000, start: 3, end: 5, text: 'b' },
    ];
    const s = run(initialState(3), { type: 'lines', lines: early, atId: 3000 });
    expect(step(s, { type: 'prev', now: 0 }).actions[0]).toEqual({ type: 'seek', time: 0 });
  });
});

describe('다시 / jump', () => {
  test('다시: 현재 줄 시작으로, 줄이 없으면 처음 연 시각으로', () => {
    expect(step(withLines(1), { type: 'replay', now: 0 }).actions).toEqual([{ type: 'seek', time: 4 - START_LEAD_S }, { type: 'play' }]);
    expect(step(initialState(4), { type: 'replay', now: 0 }).actions[0]).toEqual({ type: 'seek', time: 4 - START_LEAD_S });
  });

  test('jump는 그 줄로 가고, 범위 밖이면 무시한다', () => {
    const r = step(withLines(0), { type: 'jump', index: 2, now: 0 });
    expect(r.state.index).toBe(2);
    expect(r.actions[0]).toEqual({ type: 'seek', time: 7 - START_LEAD_S });
    const s = withLines(0);
    expect(step(s, { type: 'jump', index: 3, now: 0 }).state).toBe(s);
    expect(step(s, { type: 'jump', index: -1, now: 0 }).state).toBe(s);
  });
});

describe('tick', () => {
  test('재생 시각을 따라 현재 줄이 바뀐다(줄 시작 0.12초 전부터 다음 줄)', () => {
    const s = withLines(0);
    expect(step(s, { type: 'tick', time: 3.8, now: 0 }).state.index).toBe(0);
    expect(step(s, { type: 'tick', time: 3.9, now: 0 }).state.index).toBe(1);
    expect(step(s, { type: 'tick', time: 100, now: 0 }).state.index).toBe(2);
  });

  test('줄 사이 틈은 앞 줄, 첫 줄 이전은 첫 줄', () => {
    expect(step(withLines(1), { type: 'tick', time: 3.5, now: 0 }).state.index).toBe(0);
    expect(step(withLines(1), { type: 'tick', time: 0, now: 0 }).state.index).toBe(0);
  });

  test('같은 줄이면 상태 객체를 그대로 돌려준다', () => {
    const s = withLines(1);
    const r = step(s, { type: 'tick', time: 5, now: 0 });
    expect(r.state).toBe(s);
    expect(r.actions).toEqual([]);
  });

  test('이동 직후 SEEK_GUARD_MS 동안은 낡은 시각을 무시하고, 끝나는 순간부터 따른다', () => {
    const moved = step(withLines(0), { type: 'next', now: 1000 }).state;
    expect(step(moved, { type: 'tick', time: 1.2, now: 1000 + SEEK_GUARD_MS - 1 }).state).toBe(moved);
    expect(step(moved, { type: 'tick', time: 1.2, now: 1000 + SEEK_GUARD_MS }).state.index).toBe(0);
  });

  test('줄 정보가 없으면 무시한다', () => {
    const s = initialState(4);
    expect(step(s, { type: 'tick', time: 10, now: 0 }).state).toBe(s);
  });
});

describe('재생 상태', () => {
  test('status는 재생 여부를 기록하고 같으면 그대로 둔다', () => {
    const s = initialState(0);
    const playing = step(s, { type: 'status', playing: true }).state;
    expect(playing.playing).toBe(true);
    expect(step(playing, { type: 'status', playing: true }).state).toBe(playing);
  });

  test('toggle: 재생 중이면 멈추고 멈춰 있으면 재생한다', () => {
    expect(step(withLines(0, { playing: true }), { type: 'toggle' }).actions).toEqual([{ type: 'pause' }]);
    expect(step(withLines(0, { playing: false }), { type: 'toggle' }).actions).toEqual([{ type: 'play' }]);
  });
});

describe('시트 열림 동안 멈춤', () => {
  test('재생 중에 열면 멈추고, 닫으면 다시 재생한다', () => {
    const opened = step(withLines(1, { playing: true }), { type: 'hold' });
    expect(opened.actions).toEqual([{ type: 'pause' }]);
    const paused = run(opened.state, { type: 'status', playing: false });
    const closed = step(paused, { type: 'release' });
    expect(closed.actions).toEqual([{ type: 'play' }]);
    expect(closed.state.resumeAfterHold).toBe(false);
  });

  test('멈춰 있을 때 열면 아무것도 하지 않고, 닫아도 재생하지 않는다', () => {
    const s = withLines(1, { playing: false });
    const opened = step(s, { type: 'hold' });
    expect(opened.state).toBe(s);
    expect(opened.actions).toEqual([]);
    expect(step(s, { type: 'release' }).actions).toEqual([]);
  });

  test('열린 채 줄을 옮기면 닫을 때 다시 재생하지 않는다(이동이 이미 재생한다)', () => {
    const held = step(withLines(0, { playing: true }), { type: 'hold' }).state;
    const moved = step(held, { type: 'next', now: 0 }).state;
    expect(moved.resumeAfterHold).toBe(false);
    expect(step(moved, { type: 'release' }).actions).toEqual([]);
  });
});

describe('순수성', () => {
  test('입력 상태를 바꾸지 않는다', () => {
    const s = Object.freeze(withLines(0, { playing: true }));
    const events: PlayerEvent[] = [
      { type: 'next', now: 1 },
      { type: 'prev', now: 1 },
      { type: 'replay', now: 1 },
      { type: 'tick', time: 5, now: 1 },
      { type: 'hold' },
      { type: 'toggle' },
    ];
    for (const e of events) expect(() => step(s, e)).not.toThrow();
  });
});

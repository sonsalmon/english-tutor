import { describe, expect, test } from 'bun:test';
import type { ClipLine } from './api';
import {
  clampSync,
  formatSync,
  lineFill,
  loadSync,
  parseSyncMap,
  saveSync,
  shiftLines,
  stepSync,
  SYNC_KEY,
  SYNC_MAX_MS,
  SYNC_MAX_VIDEOS,
} from './captionTune';
import { END_LEAD_S, initialState, step, type PlayerState } from './playerMachine';

const lines: ClipLine[] = [
  { id: 1, start: 10, end: 13, text: 'one' },
  { id: 2, start: 13, end: 16, text: 'two' },
  { id: 3, start: 16, end: 19, text: 'three' },
];

function memory(initial: Record<string, unknown> | null = null) {
  const store = new Map<string, string>();
  if (initial !== null) store.set(SYNC_KEY, JSON.stringify(initial));
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    raw: () => JSON.parse(store.get(SYNC_KEY) ?? 'null'),
  };
}

describe('싱크 계산', () => {
  test('stepSync: 0.1초씩 움직이고 소수 오차 없이 ms 정수로 남는다', () => {
    let ms = 0;
    for (let i = 0; i < 3; i++) ms = stepSync(ms, 1);
    expect(ms).toBe(300);
    for (let i = 0; i < 5; i++) ms = stepSync(ms, -1);
    expect(ms).toBe(-200);
  });

  test('한도 밖으로 나가지 않고, 이상한 값은 0이며, -0은 0으로 정리한다', () => {
    expect(stepSync(SYNC_MAX_MS, 1)).toBe(SYNC_MAX_MS);
    expect(stepSync(-SYNC_MAX_MS, -1)).toBe(-SYNC_MAX_MS);
    expect(clampSync(Number.NaN)).toBe(0);
    expect(clampSync(Number.POSITIVE_INFINITY)).toBe(0);
    expect(Object.is(clampSync(-30), 0)).toBe(true);
    expect(clampSync(149)).toBe(100);
  });

  test('formatSync: 부호와 소수 한 자리', () => {
    expect(formatSync(0)).toBe('0.0초');
    expect(formatSync(300)).toBe('+0.3초');
    expect(formatSync(-1200)).toBe('-1.2초');
  });
});

describe('영상별 싱크 저장', () => {
  test('저장한 값을 영상마다 따로 읽고, 없는 영상은 0이다', () => {
    const storage = memory();
    saveSync('aaa', 300, storage);
    saveSync('bbb', -200, storage);
    expect(loadSync('aaa', storage)).toBe(300);
    expect(loadSync('bbb', storage)).toBe(-200);
    expect(loadSync('ccc', storage)).toBe(0);
  });

  test('0으로 돌리면 그 영상 칸을 지운다', () => {
    const storage = memory({ aaa: 300, bbb: 100 });
    saveSync('aaa', 0, storage);
    expect(storage.raw()).toEqual({ bbb: 100 });
  });

  test('깨진 JSON, 엉뚱한 값, 막힌 저장소에도 던지지 않는다', () => {
    expect(loadSync('aaa', { getItem: () => '{not json' })).toBe(0);
    expect(loadSync('aaa', { getItem: () => { throw new Error('blocked'); } })).toBe(0);
    expect(() => saveSync('aaa', 100, { getItem: () => null, setItem: () => { throw new Error('quota'); } })).not.toThrow();
    expect(parseSyncMap({ a: 'x', b: 90000, c: 0, d: 150 })).toEqual({ b: SYNC_MAX_MS, d: 200 });
    expect(parseSyncMap([1, 2])).toEqual({});
    expect(parseSyncMap(null)).toEqual({});
  });

  test('영상 수가 넘치면 가장 오래 안 만진 영상부터 잊는다', () => {
    const storage = memory();
    for (let i = 0; i < SYNC_MAX_VIDEOS + 3; i++) saveSync(`v${i}`, 100, storage);
    const map = storage.raw() as Record<string, number>;
    expect(Object.keys(map).length).toBe(SYNC_MAX_VIDEOS);
    expect(map.v0).toBeUndefined();
    expect(map.v2).toBeUndefined();
    expect(map.v3).toBe(100);
    saveSync('v3', 200, storage);
    expect(Object.keys(storage.raw()).at(-1)).toBe('v3');
  });
});

describe('줄 시각 밀기', () => {
  test('shiftLines: 시작과 끝을 같은 만큼 밀고 id와 글은 그대로, 0이면 같은 배열', () => {
    const later = shiftLines(lines, 300);
    expect(later.map((l) => [l.id, l.start, l.end, l.text])).toEqual([
      [1, 10.3, 13.3, 'one'],
      [2, 13.3, 16.3, 'two'],
      [3, 16.3, 19.3, 'three'],
    ]);
    expect(shiftLines(lines, 0)).toBe(lines);
    expect(lines[0].start).toBe(10);
  });

  test('0초 밑으로는 내려가지 않는다', () => {
    const early = shiftLines([{ id: 1, start: 0.1, end: 2, text: 'x' }], -500);
    expect(early[0].start).toBe(0);
    expect(early[0].end).toBeCloseTo(1.5, 9);
  });

  test('싱크를 +1초로 밀면 줄 끝 멈춤도 1초 늦게 일어난다(머신에 밀린 줄을 넣는다)', () => {
    const run = (offsetMs: number, time: number): PlayerState => {
      let state = initialState(10, null, { rate: 1, repeat: 'off', autoPause: true });
      state = step(state, { type: 'lines', lines: shiftLines(lines, offsetMs), atId: 1 }).state;
      return step(state, { type: 'tick', time, now: 10_000 }).state;
    };
    const justBeforeEnd = 13 - END_LEAD_S + 0.01;
    expect(run(0, justBeforeEnd).held).toBe(true);
    expect(run(1000, justBeforeEnd).held).toBe(false);
    expect(run(1000, justBeforeEnd + 1).held).toBe(true);
  });
});

describe('줄 안 진행 비율', () => {
  test('줄 시작 0, 끝 1, 가운데 0.5, 범위 밖은 잘라낸다', () => {
    const line = lines[0];
    expect(lineFill(line, 10)).toBe(0);
    expect(lineFill(line, 11.5)).toBe(0.5);
    expect(lineFill(line, 13)).toBe(1);
    expect(lineFill(line, 9)).toBe(0);
    expect(lineFill(line, 20)).toBe(1);
  });

  test('아주 짧은 줄도 0으로 나누지 않는다(재생기가 쓰는 끝 시각 기준)', () => {
    const tiny = { id: 9, start: 5, end: 5, text: 'x' };
    expect(lineFill(tiny, 5.15)).toBeCloseTo(0.5, 9);
    expect(lineFill(tiny, 5.3)).toBe(1);
  });
});

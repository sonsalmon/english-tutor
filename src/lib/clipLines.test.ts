import { describe, expect, test } from 'bun:test';
import type { ClipLine, ClipSegments } from './api';
import { shiftLines } from './captionTune';
import { canAutoScroll, indexOfId, lineIndexAt, lineSource, mergeSegments, sourceLine } from './clipLines';

const lines: ClipLine[] = [
  { id: 1000, start: 1, end: 3, text: 'one' },
  { id: 4000, start: 4, end: 6, text: 'two' },
  { id: 7000, start: 7, end: 9, text: 'three' },
];

describe('lineIndexAt', () => {
  test('첫 줄보다 앞이면 -1', () => {
    expect(lineIndexAt(lines, 0)).toBe(-1);
    expect(lineIndexAt(lines, 0.999)).toBe(-1);
  });

  test('줄 시작 시각부터 그 줄이다', () => {
    expect(lineIndexAt(lines, 1)).toBe(0);
    expect(lineIndexAt(lines, 4)).toBe(1);
    expect(lineIndexAt(lines, 8.9)).toBe(2);
  });

  test('줄 사이 틈에서는 앞 줄', () => {
    expect(lineIndexAt(lines, 3)).toBe(0);
    expect(lineIndexAt(lines, 3.99)).toBe(0);
    expect(lineIndexAt(lines, 6.5)).toBe(1);
  });

  test('마지막 줄이 끝난 뒤에도 마지막 줄', () => {
    expect(lineIndexAt(lines, 9)).toBe(2);
    expect(lineIndexAt(lines, 1000)).toBe(2);
  });

  test('줄이 없으면 -1', () => {
    expect(lineIndexAt([], 5)).toBe(-1);
  });
});

describe('mergeSegments', () => {
  const prev: ClipSegments = { lines: lines.slice(1), atId: 4000, hasMoreBefore: true, hasMoreAfter: true };

  test('위로 더 불러오면 앞에 붙고 겹치는 줄은 한 번만 남는다. 위쪽 더 있음은 새 답을 따른다', () => {
    const next: ClipSegments = { lines: lines.slice(0, 2), atId: 1000, hasMoreBefore: false, hasMoreAfter: true };
    const merged = mergeSegments(prev, next, 'before');
    expect(merged.lines.map((l) => l.id)).toEqual([1000, 4000, 7000]);
    expect(merged.hasMoreBefore).toBe(false);
    expect(merged.hasMoreAfter).toBe(true);
    expect(merged.atId).toBe(4000);
  });

  test('아래로 더 불러오면 뒤에 붙고 아래쪽 더 있음만 바뀐다', () => {
    const later: ClipLine[] = [{ id: 10000, start: 10, end: 12, text: 'four' }];
    const merged = mergeSegments(prev, { lines: [lines[2], ...later], atId: 7000, hasMoreBefore: true, hasMoreAfter: false }, 'after');
    expect(merged.lines.map((l) => l.id)).toEqual([4000, 7000, 10000]);
    expect(merged.hasMoreBefore).toBe(true);
    expect(merged.hasMoreAfter).toBe(false);
  });

  test('받은 줄이 순서가 뒤섞여 있어도 시간 순으로 세우고 입력을 바꾸지 않는다', () => {
    const frozen = Object.freeze({ ...prev, lines: Object.freeze([...prev.lines]) as ClipLine[] });
    const merged = mergeSegments(frozen, { lines: [lines[2], lines[0]], atId: null, hasMoreBefore: false, hasMoreAfter: false }, 'before');
    expect(merged.lines.map((l) => l.id)).toEqual([1000, 4000, 7000]);
    expect(prev.lines.length).toBe(2);
  });
});

describe('canAutoScroll', () => {
  test('사용자가 목록을 움직인 뒤 3초가 지나기 전에는 따라가지 않고, 3초부터 따라간다', () => {
    expect(canAutoScroll(10_000, 8000, 3000)).toBe(false);
    expect(canAutoScroll(10_999, 8000, 3000)).toBe(false);
    expect(canAutoScroll(11_000, 8000, 3000)).toBe(true);
  });

  test('움직인 적이 없으면 언제나 따라간다', () => {
    expect(canAutoScroll(0, Number.NEGATIVE_INFINITY, 3000)).toBe(true);
  });
});

describe('indexOfId', () => {
  test('id로 위치를 찾고 없으면 -1', () => {
    expect(indexOfId(lines, 4000)).toBe(1);
    expect(indexOfId(lines, 123)).toBe(-1);
    expect(indexOfId(lines, null)).toBe(-1);
    expect(indexOfId(lines, undefined)).toBe(-1);
  });
});

describe('lineSource', () => {
  test('영상 ID·줄 시작 초(내림)·제목을 담는다', () => {
    expect(lineSource('abcDEF12345', 'Friends S3', { id: 66500, start: 66.5, end: 69, text: 'x' })).toEqual({ video_id: 'abcDEF12345', t: 66, title: 'Friends S3' });
  });

  test('음수 시작은 0초', () => {
    expect(lineSource('abcDEF12345', 't', { id: 0, start: -0.2, end: 1, text: 'x' }).t).toBe(0);
  });

  test('싱크가 0이 아니어도 저장 시각은 줄의 원래 시작이다(밀린 줄을 그대로 넣으면 틀린다)', () => {
    const original = [{ id: 66500, start: 66.5, end: 69, text: 'x' }];
    const shifted = shiftLines(original, 1500);
    expect(lineSource('abcDEF12345', 't', shifted[0]).t).toBe(68);
    expect(lineSource('abcDEF12345', 't', sourceLine(original, shifted[0])).t).toBe(66);
    expect(lineSource('abcDEF12345', 't', sourceLine(original, shiftLines(original, -2000)[0])).t).toBe(66);
  });
});

describe('sourceLine', () => {
  test('같은 id가 없으면 받은 줄 그대로', () => {
    const stray = { id: 5, start: 1, end: 2, text: 'y' };
    expect(sourceLine(lines, stray)).toBe(stray);
  });
});

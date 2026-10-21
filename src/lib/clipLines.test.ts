import { describe, expect, test } from 'bun:test';
import type { ClipLine } from './api';
import { indexOfId, lineIndexAt, lineSource } from './clipLines';

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
});

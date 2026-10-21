import { describe, expect, test } from 'bun:test';
import { clipHash, parseClipParam } from './clipRoute';

describe('clip 주소', () => {
  test('clipHash는 #/clip/<id>?t=<초>로 만들고 줄 시작 소수점(376.8)을 정수로 내리지 않는다', () => {
    expect(clipHash('dQw4w9WgXcQ', 66)).toBe('#/clip/dQw4w9WgXcQ?t=66');
    expect(clipHash('dQw4w9WgXcQ', 376.8)).toBe('#/clip/dQw4w9WgXcQ?t=376.8');
    expect(clipHash('dQw4w9WgXcQ', 12.3456)).toBe('#/clip/dQw4w9WgXcQ?t=12.35');
    expect(clipHash('dQw4w9WgXcQ', -3)).toBe('#/clip/dQw4w9WgXcQ?t=0');
  });

  test('parseClipParam은 id와 시각을 돌려준다', () => {
    expect(parseClipParam('dQw4w9WgXcQ?t=66')).toEqual({ videoId: 'dQw4w9WgXcQ', t: 66 });
    expect(parseClipParam('dQw4w9WgXcQ?t=12.5')).toEqual({ videoId: 'dQw4w9WgXcQ', t: 12.5 });
  });

  test('시각이 없거나 틀리면 0초, id가 틀리면 null', () => {
    expect(parseClipParam('dQw4w9WgXcQ')).toEqual({ videoId: 'dQw4w9WgXcQ', t: 0 });
    expect(parseClipParam('dQw4w9WgXcQ?t=abc')).toEqual({ videoId: 'dQw4w9WgXcQ', t: 0 });
    expect(parseClipParam('dQw4w9WgXcQ?t=-5')).toEqual({ videoId: 'dQw4w9WgXcQ', t: 0 });
    expect(parseClipParam(null)).toBeNull();
    expect(parseClipParam('')).toBeNull();
    expect(parseClipParam('../etc?t=1')).toBeNull();
    expect(parseClipParam('abc?t=1')).toBeNull();
  });
});

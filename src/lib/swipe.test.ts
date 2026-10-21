import { describe, expect, test } from 'bun:test';
import { classifySwipe, EDGE_PX, MAX_DY, MIN_DX } from './swipe';

const base = { startX: 100, startY: 300, endY: 300, pointerType: 'touch' };

describe('classifySwipe', () => {
  test('오른쪽으로 충분히 밀면 right', () => {
    expect(classifySwipe({ ...base, endX: 100 + MIN_DX })).toBe('right');
  });

  test('왼쪽으로 충분히 밀면 left', () => {
    expect(classifySwipe({ ...base, endX: 100 - MIN_DX })).toBe('left');
  });

  test('왼쪽 가장자리 24px 안에서 시작하면 거부한다', () => {
    expect(classifySwipe({ ...base, startX: EDGE_PX - 1, endX: 200 })).toBeNull();
    expect(classifySwipe({ ...base, startX: EDGE_PX, endX: EDGE_PX + MIN_DX })).toBe('right');
  });

  test('72px에 못 미치면 거부한다', () => {
    expect(classifySwipe({ ...base, endX: 100 + MIN_DX - 1 })).toBeNull();
    expect(classifySwipe({ ...base, endX: 100 - MIN_DX + 1 })).toBeNull();
  });

  test('세로로 40px 이상 움직이면 거부한다', () => {
    expect(classifySwipe({ ...base, endX: 220, endY: 300 + MAX_DY })).toBeNull();
    expect(classifySwipe({ ...base, endX: 220, endY: 300 - MAX_DY })).toBeNull();
    expect(classifySwipe({ ...base, endX: 220, endY: 300 + MAX_DY - 1 })).toBe('right');
  });

  test('마우스는 무시한다', () => {
    expect(classifySwipe({ ...base, endX: 300, pointerType: 'mouse' })).toBeNull();
    expect(classifySwipe({ ...base, endX: 300, pointerType: 'pen' })).toBe('right');
  });
});

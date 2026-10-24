import { describe, expect, test } from 'bun:test';
import { MIC_MESSAGE, NETWORK_MESSAGE, friendlyError } from './errors';

describe('friendlyError', () => {
  test('TypeError("Failed to fetch")는 서버 연결 안내가 된다', () => {
    const msg = friendlyError(new TypeError('Failed to fetch'));
    expect(msg).toBe(NETWORK_MESSAGE);
    expect(msg).toContain('Tailscale');
  });

  test('네트워크와 상관없는 TypeError(코드 오류)는 Tailscale 안내가 되지 않는다', () => {
    expect(friendlyError(new TypeError("Cannot read properties of undefined (reading 'x')"))).not.toBe(NETWORK_MESSAGE);
  });

  test('Error("Load failed")도 서버 연결 안내가 된다', () => {
    expect(friendlyError(new Error('Load failed'))).toBe(NETWORK_MESSAGE);
  });

  test('NotAllowedError(마이크 거부)는 iPhone 설정 안내가 된다', () => {
    const msg = friendlyError(new DOMException('Permission denied', 'NotAllowedError'));
    expect(msg).toBe(MIC_MESSAGE);
    expect(msg).toContain('iPhone 설정');
  });

  test('알 수 없는 값은 영어 없는 한국어 기본 문구가 된다', () => {
    for (const value of [undefined, null, 42, { code: 500 }, new Error('boom')]) {
      const msg = friendlyError(value);
      expect(msg).not.toMatch(/[A-Za-z]/);
      expect(msg.length).toBeGreaterThan(0);
    }
  });

  test('직접 정한 fallback과 서버의 한국어 메시지는 살린다', () => {
    expect(friendlyError(new Error('boom'), '메시지를 보내지 못했어요.')).toBe('메시지를 보내지 못했어요.');
    expect(friendlyError(new Error('대화가 너무 길어요.'))).toBe('대화가 너무 길어요.');
  });
});

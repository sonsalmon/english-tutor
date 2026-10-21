import { describe, expect, test } from 'bun:test';
import { NAV_ITEMS, hidesTabBar, navRouteOf } from './nav';

describe('nav', () => {
  test('탭은 통화, 단어장, 클립, 설정 네 개다', () => {
    expect(NAV_ITEMS.map((i) => i.route)).toEqual(['home', 'words', 'feed', 'settings']);
  });

  test('하위 화면은 통화 탭, 발음 진단만 설정 탭에 속한다', () => {
    for (const route of ['person', 'chat', 'log', 'missions', 'topic', 'teachback', 'summary', 'replay'] as const) {
      expect(navRouteOf(route)).toBe('home');
    }
    expect(navRouteOf('pron')).toBe('settings');
    expect(navRouteOf('words')).toBe('words');
  });

  test('탭바는 통화 중 채팅과 폰의 통화 내역 상세에서 숨긴다', () => {
    expect(hidesTabBar('chat', 'jake')).toBe(true);
    expect(hidesTabBar('log', '2026-10-20-210300')).toBe(true);
    expect(hidesTabBar('log', null)).toBe(false);
    expect(hidesTabBar('person', 'jake')).toBe(false);
  });
});

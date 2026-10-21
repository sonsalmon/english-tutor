import { afterEach, describe, expect, test } from 'bun:test';
import { PARTNERS } from './partners';
import { HIDDEN_PARTNER_IDS, loadShowAllFriends, saveShowAllFriends, visibleFriends, visiblePartners } from './visibility';

const ids = (list: { id: string }[]) => list.map((p) => p.id).sort();

describe('visiblePartners', () => {
  test('기본은 Ms. Park과 Jake, Priya, Brian만 보인다', () => {
    expect(ids(visiblePartners(false))).toEqual(['brian', 'jake', 'park', 'priya']);
  });

  test('모두 보기를 켜면 전부 보인다', () => {
    expect(ids(visiblePartners(true))).toEqual(ids(PARTNERS));
    expect(visiblePartners(true).length - visiblePartners(false).length).toBe(HIDDEN_PARTNER_IDS.length);
  });

  test('Ms. Park은 언제나 맨 앞에 있고 visibleFriends에는 없다', () => {
    expect(visiblePartners(false)[0].id).toBe('park');
    expect(ids(visibleFriends(false))).toEqual(['brian', 'jake', 'priya']);
  });
});

describe('모두 보기 저장', () => {
  const store = new Map<string, string>();
  const fake = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
  (globalThis as unknown as { window: unknown }).window = { localStorage: fake };
  afterEach(() => store.clear());

  test('기본은 꺼짐, 켜면 "1"로 저장되고 끄면 지워진다', () => {
    expect(loadShowAllFriends()).toBe(false);
    saveShowAllFriends(true);
    expect(store.get('english-tutor.show-all-friends')).toBe('1');
    expect(loadShowAllFriends()).toBe(true);
    saveShowAllFriends(false);
    expect(store.has('english-tutor.show-all-friends')).toBe(false);
  });
});

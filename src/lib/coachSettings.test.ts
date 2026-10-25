import { describe, expect, test } from 'bun:test';
import {
  CORRECTION_KEY,
  DEFAULT_COACH_SETTINGS,
  FRIEND_COACH_KEY,
  loadCoachSettings,
  loadCorrection,
  loadFriendCoach,
  saveCorrection,
  saveFriendCoach,
} from './coachSettings';

function memory(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v) };
}

describe('correction strength storage', () => {
  test('defaults to normal and ignores unknown values', () => {
    expect(DEFAULT_COACH_SETTINGS).toEqual({ correction: 'normal', friendCoach: false });
    expect(loadCorrection(memory())).toBe('normal');
    expect(loadCorrection(memory({ [CORRECTION_KEY]: 'strict' }))).toBe('normal');
    expect(loadCorrection(null)).toBe('normal');
  });

  test('saves and loads each strength', () => {
    for (const strength of ['off', 'light', 'normal'] as const) {
      const store = memory();
      saveCorrection(strength, store);
      expect(store.data[CORRECTION_KEY]).toBe(strength);
      expect(loadCorrection(store)).toBe(strength);
    }
  });

  test('a broken storage falls back to the default instead of throwing', () => {
    const broken = {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
    };
    expect(loadCorrection(broken)).toBe('normal');
    expect(loadFriendCoach(broken)).toBe(false);
    expect(() => saveCorrection('off', broken)).not.toThrow();
    expect(() => saveFriendCoach(true, broken)).not.toThrow();
  });
});

describe('friend coach storage', () => {
  test('is off by default and only an explicit on turns it on', () => {
    expect(loadFriendCoach(memory())).toBe(false);
    expect(loadFriendCoach(memory({ [FRIEND_COACH_KEY]: 'yes' }))).toBe(false);
    expect(loadFriendCoach(memory({ [FRIEND_COACH_KEY]: 'on' }))).toBe(true);
  });

  test('saves on and off', () => {
    const store = memory();
    saveFriendCoach(true, store);
    expect(loadFriendCoach(store)).toBe(true);
    saveFriendCoach(false, store);
    expect(loadFriendCoach(store)).toBe(false);
  });

  test('loadCoachSettings reads both values together', () => {
    const store = memory();
    saveCorrection('light', store);
    saveFriendCoach(true, store);
    expect(loadCoachSettings(store)).toEqual({ correction: 'light', friendCoach: true });
  });
});

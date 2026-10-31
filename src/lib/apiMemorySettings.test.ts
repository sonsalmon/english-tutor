import { describe, expect, test } from 'bun:test';
import { ABOUT_ME_MAX, DEFAULT_MEMORY_SETTINGS, parseMemorySettings } from './apiMemorySettings';

describe('parseMemorySettings', () => {
  test('reads a well-formed server response', () => {
    const data = { version: 1, about_me: '  I run a Go club.  ', remember: { facts: false, threads: true, interests: false }, updated: '2026-10-31T09:00:00+09:00' };
    expect(parseMemorySettings(data)).toEqual({ about_me: 'I run a Go club.', remember: { facts: false, threads: true, interests: false } });
  });

  test('anything that is not an object gives the defaults', () => {
    for (const bad of [null, undefined, 'x', 7, [], true]) expect(parseMemorySettings(bad)).toEqual(DEFAULT_MEMORY_SETTINGS);
  });

  test('a wrongly shaped field falls back on its own without touching the others', () => {
    expect(parseMemorySettings({ about_me: 5, remember: { facts: false, threads: 'no', interests: 0 } })).toEqual({
      about_me: '',
      remember: { facts: false, threads: true, interests: true },
    });
    expect(parseMemorySettings({ about_me: 'hi', remember: 'off' })).toEqual({ about_me: 'hi', remember: DEFAULT_MEMORY_SETTINGS.remember });
  });

  test('the about_me text is capped at the server limit', () => {
    expect(parseMemorySettings({ about_me: 'a'.repeat(ABOUT_ME_MAX + 50) }).about_me.length).toBe(ABOUT_ME_MAX);
  });

  test('the defaults are all on with an empty text', () => {
    expect(DEFAULT_MEMORY_SETTINGS).toEqual({ about_me: '', remember: { facts: true, threads: true, interests: true } });
  });
});

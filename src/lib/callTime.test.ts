import { describe, expect, test } from 'bun:test';
import { parseTimeLimits, type TimeLimits } from './api';
import { ELAPSED_NOTICE_SEC, elapsedNoticeText, elapsedSeconds, nextElapsedNotice, shouldOfferRedial, timeLimitFor } from './callTime';

const LIMITS: TimeLimits = { call: 600, teachback: 900, smalltalk: null };

describe('time limit by call mode', () => {
  test('friend (smalltalk) calls have no limit, the others keep theirs', () => {
    expect(timeLimitFor('smalltalk', LIMITS)).toBeNull();
    expect(timeLimitFor('freetalk', LIMITS)).toBe(600);
    expect(timeLimitFor('mission', LIMITS)).toBe(600);
    expect(timeLimitFor('teachback', LIMITS)).toBe(900);
  });
});

describe('time limits from the server', () => {
  test('a null or missing smalltalk limit means no limit, a number keeps the countdown', () => {
    expect(parseTimeLimits({ time_limits: { call: 180, teachback: 900, smalltalk: null } })).toEqual({ call: 180, teachback: 900, smalltalk: null });
    expect(parseTimeLimits({ time_limits: { call: 180, teachback: 900 } }).smalltalk).toBeNull();
    expect(parseTimeLimits({ time_limits: { smalltalk: 420 } }).smalltalk).toBe(420);
  });

  test('a broken response falls back to the defaults for the limited modes', () => {
    expect(parseTimeLimits(null)).toEqual({ call: 600, teachback: 900, smalltalk: null });
  });
});

describe('elapsed seconds', () => {
  test('counts from the live moment and subtracts paused time', () => {
    expect(elapsedSeconds(100_000, null, 0)).toBe(0);
    expect(elapsedSeconds(100_000, 40_000, 0)).toBe(60);
    expect(elapsedSeconds(100_000, 40_000, 20_000)).toBe(40);
  });

  test('while paused the clock stays at the moment of the pause', () => {
    expect(elapsedSeconds(500_000, 40_000, 0, 100_000)).toBe(60);
  });

  test('never goes negative', () => {
    expect(elapsedSeconds(10_000, 40_000, 0)).toBe(0);
  });
});

describe('elapsed notice timing', () => {
  test('nothing before the first interval, first notice exactly at 10 minutes', () => {
    expect(nextElapsedNotice(0, 0)).toBeNull();
    expect(nextElapsedNotice(ELAPSED_NOTICE_SEC - 1, 0)).toBeNull();
    expect(nextElapsedNotice(ELAPSED_NOTICE_SEC, 0)).toEqual({ count: 1, minutes: 10 });
  });

  test('each interval fires once: later ticks of the same interval stay quiet', () => {
    expect(nextElapsedNotice(ELAPSED_NOTICE_SEC + 5, 1)).toBeNull();
    expect(nextElapsedNotice(2 * ELAPSED_NOTICE_SEC - 1, 1)).toBeNull();
    expect(nextElapsedNotice(2 * ELAPSED_NOTICE_SEC, 1)).toEqual({ count: 2, minutes: 20 });
  });

  test('a skipped stretch (tab asleep) reports only the latest interval', () => {
    expect(nextElapsedNotice(3 * ELAPSED_NOTICE_SEC + 30, 0)).toEqual({ count: 3, minutes: 30 });
  });

  test('a custom interval works and the text carries the minutes', () => {
    expect(nextElapsedNotice(120, 0, 60)).toEqual({ count: 2, minutes: 2 });
    expect(elapsedNoticeText(10)).toContain('10');
  });
});

describe('redial offer', () => {
  test('only a friend call that dropped on its own offers a redial', () => {
    expect(shouldOfferRedial('smalltalk', 'dropped')).toBe(true);
    for (const reason of ['hangup', 'time_limit', 'pause_limit', 'mission_complete', null] as const) {
      expect(shouldOfferRedial('smalltalk', reason)).toBe(false);
    }
    for (const mode of ['freetalk', 'mission', 'teachback'] as const) expect(shouldOfferRedial(mode, 'dropped')).toBe(false);
  });
});

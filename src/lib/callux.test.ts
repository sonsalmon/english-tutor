import { describe, expect, test } from 'bun:test';
import { MAX_SEGMENTS, TURN_GAP_MS, TurnTape, micNoticeText, parseCallNotice, pickRecorderMime } from './callux';

describe('parseCallNotice', () => {
  test('reads thinking on and off', () => {
    expect(parseCallNotice({ type: 'thinking', on: true })).toEqual({ kind: 'thinking', on: true });
    expect(parseCallNotice({ type: 'thinking', on: false })).toEqual({ kind: 'thinking', on: false });
    expect(parseCallNotice({ type: 'thinking' })).toEqual({ kind: 'thinking', on: true });
  });

  test('reads mic_level states and drops unknown ones', () => {
    expect(parseCallNotice({ type: 'mic_level', state: 'quiet', db: -30 })).toEqual({ kind: 'mic_level', state: 'quiet' });
    expect(parseCallNotice({ type: 'mic_level', state: 'loud' })).toBeNull();
    expect(parseCallNotice({ type: 'paused' })).toBeNull();
    expect(parseCallNotice(null)).toBeNull();
    expect(parseCallNotice('thinking')).toBeNull();
  });

  test('only quiet and noisy have a message', () => {
    expect(micNoticeText('ok')).toBeNull();
    expect(micNoticeText('quiet')).toContain('작게');
    expect(micNoticeText('noisy')).toContain('주변');
  });
});

describe('pickRecorderMime', () => {
  test('prefers mp4 (Safari), then webm, and returns null when nothing is supported', () => {
    expect(pickRecorderMime(() => true)).toBe('audio/mp4');
    expect(pickRecorderMime((t) => t.startsWith('audio/webm'))).toBe('audio/webm;codecs=opus');
    expect(pickRecorderMime(() => false)).toBeNull();
  });
});

describe('TurnTape', () => {
  test('pieces closer than the gap join one turn', () => {
    const tape = new TurnTape<string>();
    tape.begin(0);
    tape.finish('a', 1000);
    tape.begin(1000 + TURN_GAP_MS - 1);
    tape.finish('b', 5000);
    expect(tape.clips()).toEqual(['a', 'b']);
  });

  test('a later turn replaces the old one only after its first piece is finished', () => {
    const tape = new TurnTape<string>();
    tape.begin(0);
    tape.finish('old', 1000);
    tape.begin(1000 + TURN_GAP_MS);
    expect(tape.clips()).toEqual(['old']);
    tape.finish('new', 9000);
    expect(tape.clips()).toEqual(['new']);
  });

  test('an empty piece keeps the previous turn', () => {
    const tape = new TurnTape<string>();
    tape.begin(0);
    tape.finish('old', 1000);
    tape.begin(10_000);
    tape.finish(null, 10_100);
    expect(tape.clips()).toEqual(['old']);
    expect(tape.ready).toBe(true);
  });

  test('keeps only the newest pieces and clears', () => {
    const tape = new TurnTape<number>();
    tape.begin(0);
    for (let i = 0; i < MAX_SEGMENTS + 3; i += 1) {
      tape.begin(i * 10);
      tape.finish(i, i * 10 + 5);
    }
    expect(tape.clips().length).toBe(MAX_SEGMENTS);
    expect(tape.clips()[MAX_SEGMENTS - 1]).toBe(MAX_SEGMENTS + 2);
    tape.clear();
    expect(tape.ready).toBe(false);
  });
});

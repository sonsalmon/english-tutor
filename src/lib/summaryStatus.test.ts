import { describe, expect, test } from 'bun:test';
import { withSummary, type CallSummary } from './api';
import { anyRunning, parseSummaryStatus, startPolling, type Timers } from './summaryStatus';

function fakeTimers() {
  let next = 1;
  const pending = new Map<number, () => unknown>();
  const timers: Timers = {
    set: (callback) => {
      const id = next++;
      pending.set(id, callback);
      return id;
    },
    clear: (id) => {
      pending.delete(id as number);
    },
  };
  const fire = async () => {
    const [id, callback] = [...pending][0];
    pending.delete(id);
    await callback();
  };
  return { timers, pending, fire };
}

describe('parseSummaryStatus', () => {
  test('keeps the four server values', () => {
    for (const status of ['pending', 'running', 'done', 'failed'] as const) expect(parseSummaryStatus(status)).toBe(status);
  });

  test('falls back to has_tutoring for an old server or a garbled value', () => {
    expect(parseSummaryStatus(undefined, true)).toBe('done');
    expect(parseSummaryStatus(undefined, false)).toBe('pending');
    expect(parseSummaryStatus('finished', false)).toBe('pending');
    expect(parseSummaryStatus(3, true)).toBe('done');
  });

  test('withSummary reads the field from a call row', () => {
    const base = { stem: 's', has_tutoring: false } as CallSummary;
    expect(withSummary({ ...base, summary: 'running' }).summary).toBe('running');
    expect(withSummary({ ...base, has_tutoring: true } as CallSummary).summary).toBe('done');
  });
});

describe('anyRunning', () => {
  test('is true only while some call is still being summarized', () => {
    expect(anyRunning([{ summary: 'done' }, { summary: 'pending' }, { summary: 'failed' }])).toBe(false);
    expect(anyRunning([{ summary: 'done' }, { summary: 'running' }])).toBe(true);
    expect(anyRunning([])).toBe(false);
  });
});

describe('startPolling', () => {
  test('ticks once per interval and keeps going while tick says so', async () => {
    const { timers, pending, fire } = fakeTimers();
    let ticks = 0;
    startPolling(async () => ++ticks < 3, 4000, timers);
    expect(ticks).toBe(0);

    await fire();
    await fire();
    expect(ticks).toBe(2);
    expect(pending.size).toBe(1);

    await fire();
    expect(ticks).toBe(3);
    expect(pending.size).toBe(0);
  });

  test('stop() cancels the waiting timer so no tick ever runs', async () => {
    const { timers, pending } = fakeTimers();
    let ticks = 0;
    const stop = startPolling(async () => (++ticks, true), 4000, timers);

    stop();

    expect(pending.size).toBe(0);
    expect(ticks).toBe(0);
  });

  test('a tick that finishes after stop() does not schedule another', async () => {
    const { timers, pending, fire } = fakeTimers();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => (release = resolve));
    const stop = startPolling(async () => (await gate, true), 4000, timers);

    const firing = fire();
    stop();
    release();
    await firing;

    expect(pending.size).toBe(0);
  });

  test('a failing tick does not end the polling', async () => {
    const { timers, pending, fire } = fakeTimers();
    let ticks = 0;
    startPolling(async () => {
      ticks++;
      throw new Error('network');
    }, 4000, timers);

    await fire();

    expect(ticks).toBe(1);
    expect(pending.size).toBe(1);
  });
});

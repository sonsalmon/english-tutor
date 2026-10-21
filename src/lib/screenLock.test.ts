import { describe, expect, test } from 'bun:test';
import { createWakeLockKeeper, DEFAULT_SCREEN_MODE, loadScreenMode, SCREEN_MODE_KEY, saveScreenMode } from './screenLock';

function memory(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v) };
}

function fakeDoc() {
  const listeners = new Set<() => void>();
  const doc = {
    visibilityState: 'visible' as DocumentVisibilityState,
    addEventListener: (_: string, cb: () => void) => void listeners.add(cb),
    removeEventListener: (_: string, cb: () => void) => void listeners.delete(cb),
  };
  return { doc: doc as unknown as Pick<Document, 'visibilityState' | 'addEventListener' | 'removeEventListener'>, raw: doc, fire: () => listeners.forEach((cb) => cb()), count: () => listeners.size };
}

function fakeWakeLock() {
  const sentinels: { released: boolean; release: () => Promise<void> }[] = [];
  return {
    sentinels,
    request: async () => {
      const s = {
        released: false,
        release: async () => {
          s.released = true;
        },
      };
      sentinels.push(s);
      return s;
    },
  };
}

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

describe('screen mode storage', () => {
  test('defaults to keep and ignores unknown values', () => {
    expect(DEFAULT_SCREEN_MODE).toBe('keep');
    expect(loadScreenMode(memory())).toBe('keep');
    expect(loadScreenMode(memory({ [SCREEN_MODE_KEY]: 'weird' }))).toBe('keep');
  });

  test('round-trips the three modes under the agreed key', () => {
    for (const mode of ['system', 'keep', 'black'] as const) {
      const store = memory();
      saveScreenMode(mode, store);
      expect(store.data['english-tutor.screen-mode']).toBe(mode);
      expect(loadScreenMode(store)).toBe(mode);
    }
  });

  test('survives a storage that throws', () => {
    const broken = {
      getItem: () => {
        throw new Error('denied');
      },
      setItem: () => {
        throw new Error('denied');
      },
    };
    expect(loadScreenMode(broken)).toBe('keep');
    expect(() => saveScreenMode('black', broken)).not.toThrow();
  });
});

describe('wake lock keeper', () => {
  test('requests the screen lock once on start, even if start is repeated while pending', async () => {
    const lock = fakeWakeLock();
    const { doc } = fakeDoc();
    const keeper = createWakeLockKeeper(lock, doc);
    keeper.start();
    keeper.start();
    await tick();
    expect(lock.sentinels.length).toBe(1);
  });

  test('re-acquires when the page becomes visible after the system released the lock', async () => {
    const lock = fakeWakeLock();
    const { doc, raw, fire } = fakeDoc();
    const keeper = createWakeLockKeeper(lock, doc);
    keeper.start();
    await tick();
    raw.visibilityState = 'hidden';
    lock.sentinels[0].released = true;
    fire();
    await tick();
    expect(lock.sentinels.length).toBe(1);
    raw.visibilityState = 'visible';
    fire();
    await tick();
    expect(lock.sentinels.length).toBe(2);
  });

  test('stop releases the lock and the listener', async () => {
    const lock = fakeWakeLock();
    const { doc, count } = fakeDoc();
    const keeper = createWakeLockKeeper(lock, doc);
    keeper.start();
    await tick();
    keeper.stop();
    await tick();
    expect(lock.sentinels[0].released).toBe(true);
    expect(count()).toBe(0);
  });

  test('a lock granted after stop is released immediately', async () => {
    const lock = fakeWakeLock();
    const { doc } = fakeDoc();
    const keeper = createWakeLockKeeper(lock, doc);
    keeper.start();
    keeper.stop();
    await tick();
    expect(lock.sentinels.every((s) => s.released)).toBe(true);
  });

  test('a rejected request does not throw', async () => {
    const { doc } = fakeDoc();
    const keeper = createWakeLockKeeper({ request: () => Promise.reject(new Error('NotAllowed')) }, doc);
    keeper.start();
    await tick();
    keeper.stop();
  });
});

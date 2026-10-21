import { useCallback, useEffect, useRef, useState } from 'react';

export type ScreenMode = 'system' | 'keep' | 'black';

export const SCREEN_MODE_KEY = 'english-tutor.screen-mode';
export const DEFAULT_SCREEN_MODE: ScreenMode = 'keep';
export const HIDDEN_NOTICE_MS = 3000;
export const BLACK_DELAY_MS = 5000;

const MODES: readonly ScreenMode[] = ['system', 'keep', 'black'];

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>;

function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage;
  } catch {
    return null;
  }
}

export function loadScreenMode(storage: StorageLike | null = defaultStorage()): ScreenMode {
  try {
    const value = storage?.getItem(SCREEN_MODE_KEY);
    return MODES.find((m) => m === value) ?? DEFAULT_SCREEN_MODE;
  } catch {
    return DEFAULT_SCREEN_MODE;
  }
}

export function saveScreenMode(mode: ScreenMode, storage: StorageLike | null = defaultStorage()): void {
  try {
    storage?.setItem(SCREEN_MODE_KEY, mode);
  } catch {
    // 저장소를 못 쓰는 브라우저(사생활 보호 모드 등)에서는 이번 세션 값만 쓴다.
  }
}

type Sentinel = { released: boolean; release(): Promise<void> };
type WakeLockLike = { request(type: 'screen'): Promise<Sentinel> };
type DocLike = Pick<Document, 'visibilityState' | 'addEventListener' | 'removeEventListener'>;

// Wake Lock은 페이지가 숨겨지면 시스템이 풀어 버린다. 다시 보이면 새로 잡는다.
export function createWakeLockKeeper(wakeLock: WakeLockLike, doc: DocLike) {
  let sentinel: Sentinel | null = null;
  let pending = false;
  let stopped = true;

  const acquire = async () => {
    if (stopped || pending || (sentinel && !sentinel.released) || doc.visibilityState !== 'visible') return;
    pending = true;
    try {
      const next = await wakeLock.request('screen');
      if (stopped) await next.release();
      else sentinel = next;
    } catch {
      // 절전 모드 등으로 거부되면 다음에 다시 보일 때 시도한다.
    } finally {
      pending = false;
    }
  };
  const onVisible = () => void acquire();

  return {
    start() {
      stopped = false;
      doc.addEventListener('visibilitychange', onVisible);
      void acquire();
    },
    stop() {
      stopped = true;
      doc.removeEventListener('visibilitychange', onVisible);
      const held = sentinel;
      sentinel = null;
      if (held && !held.released) void held.release().catch(() => undefined);
    },
  };
}

// active인 동안 화면을 켜 둔다(mode가 system이면 아무것도 안 한다). resumed는 통화 중 화면이 3초 넘게 숨었다가 돌아왔다는 뜻이다.
export function useScreenLock(active: boolean, mode: ScreenMode) {
  const supported = typeof navigator !== 'undefined' && 'wakeLock' in navigator;
  const [resumed, setResumed] = useState(false);
  const hiddenAt = useRef<number | null>(null);

  useEffect(() => {
    if (!active || mode === 'system' || !supported) return;
    const keeper = createWakeLockKeeper(navigator.wakeLock as WakeLockLike, document);
    keeper.start();
    return () => keeper.stop();
  }, [active, mode, supported]);

  useEffect(() => {
    if (!active) {
      setResumed(false);
      return;
    }
    const onChange = () => {
      if (document.visibilityState === 'hidden') {
        hiddenAt.current = Date.now();
      } else if (hiddenAt.current !== null) {
        if (Date.now() - hiddenAt.current > HIDDEN_NOTICE_MS) setResumed(true);
        hiddenAt.current = null;
      }
    };
    document.addEventListener('visibilitychange', onChange);
    return () => document.removeEventListener('visibilitychange', onChange);
  }, [active]);

  const dismissResumed = useCallback(() => setResumed(false), []);
  return { supported, resumed, dismissResumed };
}

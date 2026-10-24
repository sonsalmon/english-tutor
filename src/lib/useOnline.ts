import { useCallback, useEffect, useRef, useState } from 'react';

const CHECK_TIMEOUT_MS = 5000;
const CHECK_EVERY_MS = 20000;

// 서버에 닿는지 /api/status로 직접 확인한다. 응답이 오더라도 5xx면 닿지 않은 것으로 본다.
async function serverReachable(): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CHECK_TIMEOUT_MS);
  try {
    const res = await fetch('/api/status', { cache: 'no-store', signal: controller.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}

// 폰의 online/offline 이벤트와 /api/status 확인을 합쳐, 서버에 닿는지 알려 준다.
// 처음에는 닿는다고 가정해 배너가 깜빡이지 않게 하고, 앞으로 돌아올 때와 20초마다 다시 확인한다.
export function useOnline(): { reachable: boolean; recheck: () => void } {
  const [reachable, setReachable] = useState(() => navigator.onLine);
  const alive = useRef(true);

  const recheck = useCallback(() => {
    if (!navigator.onLine) {
      setReachable(false);
      return;
    }
    void serverReachable().then((ok) => {
      if (alive.current) setReachable(ok);
    });
  }, []);

  useEffect(() => {
    alive.current = true;
    recheck();
    const onVisible = () => {
      if (document.visibilityState === 'visible') recheck();
    };
    const timer = setInterval(recheck, CHECK_EVERY_MS);
    window.addEventListener('online', recheck);
    window.addEventListener('offline', recheck);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive.current = false;
      clearInterval(timer);
      window.removeEventListener('online', recheck);
      window.removeEventListener('offline', recheck);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [recheck]);

  return { reachable, recheck };
}

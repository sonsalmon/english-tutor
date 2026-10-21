import { useEffect, useRef } from 'react';
import { startPolling } from './summaryStatus';

// active인 동안만 몇 초마다 refresh를 부른다. active가 꺼지거나 key가 바뀌거나 화면이 닫히면 멈추고, 날아가던 요청은 취소한다.
export function useSummaryPolling(active: boolean, refresh: (signal: AbortSignal) => Promise<void>, key: string): void {
  const latest = useRef(refresh);
  useEffect(() => {
    latest.current = refresh;
  });
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const stop = startPolling(async () => {
      await latest.current(controller.signal);
      return true;
    });
    return () => {
      stop();
      controller.abort();
    };
  }, [active, key]);
}

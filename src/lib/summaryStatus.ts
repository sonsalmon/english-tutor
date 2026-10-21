// 통화 정리(요약)가 어디까지 왔는지. 서버가 통화 목록·상세에 summary 필드로 알려 준다.
export type SummaryStatus = 'pending' | 'running' | 'done' | 'failed';

const STATUSES: readonly string[] = ['pending', 'running', 'done', 'failed'];

// 서버 값을 상태로 읽는다. 필드가 없는 옛 서버 응답은 요약 파일이 있는지(has_tutoring)로 판단한다.
export function parseSummaryStatus(value: unknown, hasTutoring = false): SummaryStatus {
  if (typeof value === 'string' && STATUSES.includes(value)) return value as SummaryStatus;
  return hasTutoring ? 'done' : 'pending';
}

export const anyRunning = (calls: readonly { summary?: SummaryStatus }[]): boolean => calls.some((c) => c.summary === 'running');

export const POLL_MS = 4000;

export type Timers = {
  set: (callback: () => void, ms: number) => unknown;
  clear: (id: unknown) => void;
};

const realTimers: Timers = {
  set: (callback, ms) => globalThis.setTimeout(callback, ms),
  clear: (id) => globalThis.clearTimeout(id as ReturnType<typeof setTimeout>),
};

// tick을 intervalMs마다 부른다. tick이 false를 돌려주면 멈추고, 돌려준 stop()을 부르면 바로 멈춘다.
// tick이 실패해도(네트워크가 잠깐 끊긴 경우) 계속 시도한다. 멈춘 뒤에 끝난 tick은 다음 차례를 걸지 않는다.
export function startPolling(tick: () => Promise<boolean>, intervalMs = POLL_MS, timers: Timers = realTimers): () => void {
  let stopped = false;
  let handle: unknown = null;
  const schedule = () => {
    handle = timers.set(async () => {
      handle = null;
      let again = true;
      try {
        again = await tick();
      } catch {
        again = true;
      }
      if (!stopped && again) schedule();
    }, intervalMs);
  };
  schedule();
  return () => {
    stopped = true;
    if (handle !== null) timers.clear(handle);
    handle = null;
  };
}

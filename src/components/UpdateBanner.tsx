import { useSyncExternalStore } from 'react';
import { getUpdateReady, shouldShowUpdateBanner, subscribeUpdateReady } from '../lib/swUpdate';

function subscribeHash(notify: () => void) {
  window.addEventListener('hashchange', notify);
  return () => window.removeEventListener('hashchange', notify);
}

// 새 버전이 준비되면 화면 위쪽에 작게 알린다. 통화 중(#/call)에는 보이지 않고, 통화를 벗어나면 나타난다.
export function UpdateBanner() {
  const ready = useSyncExternalStore(subscribeUpdateReady, getUpdateReady);
  const hash = useSyncExternalStore(subscribeHash, () => window.location.hash);
  if (!shouldShowUpdateBanner(ready, hash)) return null;
  return (
    <div
      role="status"
      className="fixed inset-x-5 top-[calc(8px+env(safe-area-inset-top))] z-50 mx-auto flex max-w-[440px] items-center justify-between gap-3 rounded-2xl bg-ink py-2 pr-2 pl-4 text-white shadow-lg"
    >
      <p className="font-semibold">새 버전이 있어요</p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        className="min-h-11 shrink-0 rounded-full bg-marker px-5 font-bold text-ink active:opacity-80"
      >
        새로고침
      </button>
    </div>
  );
}

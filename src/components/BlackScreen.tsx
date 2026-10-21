import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from 'react';

export const RELEASE_DRAG_PX = 120;
const HANDLE_VISIBLE_MS = 3000;
const HANDLE_WIDTH = 220;
const THUMB = 48;
const MAX_DRAG = HANDLE_WIDTH - THUMB - 8;

// 통화 화면을 까맣게 덮는다. 귀에 닿은 터치는 모두 무시하고, 손잡이를 오른쪽으로 120px 이상 끌어야만 풀린다.
export function BlackScreen({ onRelease }: { onRelease: () => void }) {
  const [handleVisible, setHandleVisible] = useState(false);
  const [dx, setDx] = useState(0);
  const dxRef = useRef(0);
  const hideTimer = useRef<number | null>(null);
  const drag = useRef<{ pointerId: number; startX: number } | null>(null);

  const clearTimer = () => {
    if (hideTimer.current !== null) window.clearTimeout(hideTimer.current);
    hideTimer.current = null;
  };
  const showHandle = () => {
    clearTimer();
    setHandleVisible(true);
    hideTimer.current = window.setTimeout(() => setHandleVisible(false), HANDLE_VISIBLE_MS);
  };
  useEffect(() => clearTimer, []);

  const move = (value: number) => {
    dxRef.current = value;
    setDx(value);
  };
  const onHandleDown = (e: PointerEvent<HTMLButtonElement>) => {
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { pointerId: e.pointerId, startX: e.clientX };
    clearTimer();
  };
  const onHandleMove = (e: PointerEvent<HTMLButtonElement>) => {
    if (drag.current?.pointerId === e.pointerId) move(Math.max(0, Math.min(e.clientX - drag.current.startX, MAX_DRAG)));
  };
  const onHandleUp = (e: PointerEvent<HTMLButtonElement>) => {
    if (drag.current?.pointerId !== e.pointerId) return;
    drag.current = null;
    const released = dxRef.current >= RELEASE_DRAG_PX;
    move(0);
    if (released) onRelease();
    else showHandle();
  };
  const onHandleKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === 'Enter' || e.key === ' ' || e.key === 'ArrowRight') {
      e.preventDefault();
      onRelease();
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="검은 화면. 통화는 계속되고 있어요"
      data-testid="black-screen"
      className="fixed inset-0 z-50 touch-none select-none bg-black"
      onPointerDown={(e) => {
        e.preventDefault();
        showHandle();
      }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <button
        type="button"
        aria-label="화면 켜기. 손잡이를 오른쪽으로 밀거나 Enter 키를 누르세요"
        onPointerDown={onHandleDown}
        onPointerMove={onHandleMove}
        onPointerUp={onHandleUp}
        onPointerCancel={onHandleUp}
        onKeyDown={onHandleKey}
        style={{ width: HANDLE_WIDTH }}
        className={`absolute bottom-[calc(40px+env(safe-area-inset-bottom))] left-1/2 flex h-14 -translate-x-1/2 touch-none items-center rounded-full bg-white/15 px-1 transition-opacity duration-200 focus-visible:opacity-100 ${handleVisible ? 'opacity-100' : 'pointer-events-none opacity-0'}`}
      >
        <span aria-hidden className="block rounded-full bg-white/40" style={{ width: THUMB, height: THUMB, transform: `translateX(${dx}px)` }} />
      </button>
    </div>
  );
}

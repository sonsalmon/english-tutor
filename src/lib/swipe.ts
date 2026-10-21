import { useRef, type PointerEvent as ReactPointerEvent } from 'react';

// iOS의 뒤로 가기 제스처가 화면 왼쪽 가장자리에서 시작하므로 그 안쪽에서 시작한 스와이프만 받는다.
export const EDGE_PX = 24;
export const MIN_DX = 72;
export const MAX_DY = 40;

export type SwipeInput = {
  startX: number;
  startY: number;
  endX: number;
  endY: number;
  pointerType: string;
};

export type SwipeDirection = 'right' | 'left';

// 가로로 충분히 밀었고 세로로는 거의 안 움직였을 때만 방향을 돌려준다. 마우스는 언제나 무시한다.
export function classifySwipe({ startX, startY, endX, endY, pointerType }: SwipeInput): SwipeDirection | null {
  if (pointerType === 'mouse') return null;
  if (startX < EDGE_PX) return null;
  if (Math.abs(endY - startY) >= MAX_DY) return null;
  const dx = endX - startX;
  if (dx >= MIN_DX) return 'right';
  if (dx <= -MIN_DX) return 'left';
  return null;
}

type Start = { x: number; y: number; id: number };

// 본문에 펼쳐 쓴다: <div {...swipe.handlers} style={swipe.style}>. 글자 입력칸에서 시작한 밀기는 무시한다(선택과 겹침 방지).
export function useSwipe(handlers: { onRight?: () => void; onLeft?: () => void }) {
  const start = useRef<Start | null>(null);
  const latest = useRef(handlers);
  latest.current = handlers;

  return {
    style: { touchAction: 'pan-y' as const },
    handlers: {
      onPointerDown(e: ReactPointerEvent) {
        if (e.pointerType === 'mouse' || !e.isPrimary) return;
        if ((e.target as HTMLElement).closest('textarea,input')) return;
        start.current = { x: e.clientX, y: e.clientY, id: e.pointerId };
      },
      onPointerUp(e: ReactPointerEvent) {
        const from = start.current;
        start.current = null;
        if (!from || from.id !== e.pointerId) return;
        const direction = classifySwipe({
          startX: from.x,
          startY: from.y,
          endX: e.clientX,
          endY: e.clientY,
          pointerType: e.pointerType,
        });
        if (direction === 'right') latest.current.onRight?.();
        else if (direction === 'left') latest.current.onLeft?.();
      },
      onPointerCancel() {
        start.current = null;
      },
    },
  };
}

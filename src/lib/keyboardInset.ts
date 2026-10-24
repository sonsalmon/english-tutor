import { useEffect, useState } from 'react';

export const KEYBOARD_MIN_PX = 80;

// 화면 키보드가 가린 아래쪽 높이(px). 주소창이 줄었다 늘었다 하는 작은 차이는 0으로 본다.
export function keyboardInset(innerHeight: number, viewportHeight: number, offsetTop: number): number {
  const covered = Math.round(innerHeight - viewportHeight - offsetTop);
  return covered >= KEYBOARD_MIN_PX ? covered : 0;
}

// 아이폰 홈 화면 앱은 키보드가 올라와도 레이아웃 높이(dvh)가 줄지 않아 아래 입력줄이 가린다. visualViewport로 가린 높이를 잰다.
export function useKeyboardInset(active: boolean): number {
  const [inset, setInset] = useState(0);
  useEffect(() => {
    const vv = typeof window === 'undefined' ? null : window.visualViewport;
    if (!active || !vv) {
      setInset(0);
      return;
    }
    const update = () => setInset(keyboardInset(window.innerHeight, vv.height, vv.offsetTop));
    update();
    vv.addEventListener('resize', update);
    vv.addEventListener('scroll', update);
    return () => {
      vv.removeEventListener('resize', update);
      vv.removeEventListener('scroll', update);
    };
  }, [active]);
  return inset;
}

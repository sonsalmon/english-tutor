import { BookMarked, Clapperboard, Phone, Settings, type LucideIcon } from 'lucide-react';
import type { Route } from './router';

export type NavItem = { label: string; route: Route; icon: LucideIcon };

// 사이드바와 폰 하단 탭바가 같은 네 칸을 쓴다. 옛 메뉴 항목은 모두 사람 페이지와 설정 안으로 들어갔다.
export const NAV_ITEMS: NavItem[] = [
  { label: '통화', route: 'home', icon: Phone },
  { label: '단어장', route: 'words', icon: BookMarked },
  { label: '클립', route: 'feed', icon: Clapperboard },
  { label: '설정', route: 'settings', icon: Settings },
];

// 하위 화면이 어느 탭에 속하는지. 발음 진단만 설정 아래이고 나머지는 모두 통화 탭이다.
export function navRouteOf(route: Route): Route {
  switch (route) {
    case 'person':
    case 'chat':
    case 'log':
    case 'missions':
    case 'topic':
    case 'teachback':
    case 'summary':
    case 'replay':
      return 'home';
    case 'pron':
      return 'settings';
    default:
      return route;
  }
}

// 탭바가 입력창이나 상세를 가리지 않도록 숨기는 화면: 친구와의 대화와 폰의 통화 내역 상세.
export function hidesTabBar(route: Route, param: string | null): boolean {
  return (route === 'chat' || route === 'log') && param !== null;
}

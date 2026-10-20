import {
  Briefcase,
  Coffee,
  Ellipsis,
  GraduationCap,
  History,
  House,
  MessageSquareText,
  MessagesSquare,
  Mic,
  type LucideIcon,
} from 'lucide-react';
import type { Route } from './router';

export type NavItem = { label: string; route: Route; icon: LucideIcon };

// 'chat' 경로는 router.ts의 Route에 아직 없을 수 있다(친구 채팅 화면은 다른 작업이 만든다). 그때까지 이 주소는 홈으로 간다.
const CHAT = 'chat' as string as Route;

// 사이드바 메뉴 순서. 메뉴를 늘리려면 이 배열에 항목만 추가한다.
export const NAV_ITEMS: NavItem[] = [
  { label: '홈', route: 'home', icon: House },
  { label: '스몰토크', route: 'smalltalk', icon: Coffee },
  { label: '친구 채팅', route: CHAT, icon: MessagesSquare },
  { label: '상황 역할극', route: 'missions', icon: Briefcase },
  { label: '주제 정해서 대화', route: 'topic', icon: MessageSquareText },
  { label: '가르치며 배우기', route: 'teachback', icon: GraduationCap },
  { label: '발음 진단', route: 'pron', icon: Mic },
  { label: '통화 기록', route: 'history', icon: History },
];

// 폰 하단 탭바: 자주 쓰는 4개 + "더 보기"(나머지). 탭은 5칸을 넘기지 않는다.
const TAB_ROUTES: Route[] = ['home', 'smalltalk', CHAT, 'history'];
export const TAB_ITEMS: NavItem[] = TAB_ROUTES.map((route) => NAV_ITEMS.find((item) => item.route === route)!);
export const MORE_ITEMS: NavItem[] = NAV_ITEMS.filter((item) => !TAB_ROUTES.includes(item.route));
export const MORE_ICON: LucideIcon = Ellipsis;

// 하위 화면이 어느 메뉴에 속하는지(기록 재생은 통화 기록 아래).
export function navRouteOf(route: Route): Route {
  return route === 'replay' ? 'history' : route;
}

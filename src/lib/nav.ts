import { Briefcase, Coffee, GraduationCap, History, House, MessageSquareText, type LucideIcon } from 'lucide-react';
import type { Route } from './router';

export type NavItem = { label: string; route: Route; icon: LucideIcon };

// 사이드바 메뉴 순서. 메뉴를 늘리려면 이 배열에 항목만 추가한다.
export const NAV_ITEMS: NavItem[] = [
  { label: '홈', route: 'home', icon: House },
  { label: '스몰토크', route: 'smalltalk', icon: Coffee },
  { label: '상황 역할극', route: 'missions', icon: Briefcase },
  { label: '주제 정해서 대화', route: 'topic', icon: MessageSquareText },
  { label: '가르치며 배우기', route: 'teachback', icon: GraduationCap },
  { label: '통화 기록', route: 'history', icon: History },
];

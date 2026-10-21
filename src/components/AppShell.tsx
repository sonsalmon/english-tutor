import type { ReactNode } from 'react';
import { NAV_ITEMS, hidesTabBar, navRouteOf } from '../lib/nav';
import { go, useRouteParam, type Route } from '../lib/router';
import { Portrait } from './ui';

// 통화 화면은 사이드바·탭바 없이 전체를 쓴다. 통화 중에 다른 메뉴로 나가면 통화가 끊기기 때문이다. 클립 공부 화면도 전체를 쓴다.
// 친구와의 대화(#/chat/<id>)와 폰의 통화 내역 상세(#/log/<stem>)는 탭바를 숨긴다.
export function AppShell({ route, children }: { route: Route; children: ReactNode }) {
  const param = useRouteParam();
  if (route === 'call' || route === 'clip') return <>{children}</>;
  const tabBarHidden = hidesTabBar(route, param);
  const current = navRouteOf(route);
  return (
    <div
      className={`lg:pb-0 lg:pl-60 ${
        tabBarHidden ? '' : 'pb-[calc(4rem+env(safe-area-inset-bottom))] [&>main]:min-h-[calc(100dvh-4rem-env(safe-area-inset-bottom))] lg:[&>main]:min-h-0'
      }`}
    >
      <aside className="fixed inset-y-0 left-0 z-10 hidden w-60 flex-col border-r border-line bg-surface px-3 py-6 lg:flex">
        <div className="flex items-center gap-3 px-2">
          <Portrait size={48} />
          <div className="min-w-0">
            <p className="font-bold leading-tight">English Friends</p>
            <p className="text-sm text-ink-soft">Ms. Park</p>
          </div>
        </div>
        <nav aria-label="주 메뉴" className="mt-8">
          <ul className="space-y-1">
            {NAV_ITEMS.map(({ label, route: target, icon: Icon }) => {
              const active = target === current;
              return (
                <li key={target}>
                  <button
                    type="button"
                    onClick={() => go(target)}
                    aria-current={active ? 'page' : undefined}
                    className={`flex min-h-11 w-full items-center gap-3 rounded-xl px-3 text-left font-semibold ${
                      active ? 'bg-ink text-white' : 'text-ink hover:bg-paper'
                    }`}
                  >
                    <Icon size={20} aria-hidden />
                    {label}
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>
      </aside>
      {children}
      {!tabBarHidden && <TabBar current={current} />}
    </div>
  );
}

// 폰(lg 미만) 하단 탭바. 통화·단어장·클립·설정, 모두 아이콘과 글자를 함께 쓴다.
function TabBar({ current }: { current: Route }) {
  const pill = (active: boolean) =>
    `grid h-8 w-14 place-items-center rounded-full transition-colors ${active ? 'bg-ink text-white' : 'text-ink-soft'}`;
  const tab = 'flex h-16 w-full flex-col items-center justify-center gap-0.5 text-xs font-semibold';

  return (
    <div className="lg:hidden">
      <nav aria-label="하단 메뉴" className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]">
        <ul className="mx-auto grid max-w-[480px] grid-cols-4">
          {NAV_ITEMS.map(({ label, route: target, icon: Icon }) => {
            const active = target === current;
            return (
              <li key={target}>
                <button type="button" onClick={() => go(target)} aria-current={active ? 'page' : undefined} className={`${tab} ${active ? 'text-ink' : 'text-ink-soft'}`}>
                  <span className={pill(active)}>
                    <Icon size={22} aria-hidden />
                  </span>
                  {label}
                </button>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}

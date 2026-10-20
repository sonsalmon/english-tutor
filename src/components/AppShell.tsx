import { useEffect, useState, type ReactNode } from 'react';
import { MORE_ICON, MORE_ITEMS, NAV_ITEMS, TAB_ITEMS, navRouteOf } from '../lib/nav';
import { go, useRouteParam, type Route } from '../lib/router';
import { Portrait } from './ui';

// 통화 화면은 사이드바·탭바 없이 전체를 쓴다. 통화 중에 다른 메뉴로 나가면 통화가 끊기기 때문이다.
// 친구와의 대화 화면(#/chat/<id>)은 메신저처럼 탭바를 숨기고 입력창을 맨 아래에 붙인다. 목록(#/chat)은 탭바가 있다.
export function AppShell({ route, children }: { route: Route; children: ReactNode }) {
  const param = useRouteParam();
  if (route === 'call') return <>{children}</>;
  const inConversation = route === 'chat' && param !== null;
  return (
    <div
      className={`lg:pb-0 lg:pl-60 ${
        inConversation
          ? ''
          : 'pb-[calc(4rem+env(safe-area-inset-bottom))] [&>main]:min-h-[calc(100dvh-4rem-env(safe-area-inset-bottom))] lg:[&>main]:min-h-0'
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
              const active = target === route;
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
      {!inConversation && <TabBar route={route} />}
    </div>
  );
}

// 폰(lg 미만) 하단 탭바. 홈·스몰토크·친구 채팅·통화 기록 + 나머지 메뉴를 여는 "더 보기".
function TabBar({ route }: { route: Route }) {
  const [moreOpen, setMoreOpen] = useState(false);
  const current = navRouteOf(route);
  const moreActive = MORE_ITEMS.some((item) => item.route === current);
  const MoreIcon = MORE_ICON;

  useEffect(() => setMoreOpen(false), [route]);

  useEffect(() => {
    if (!moreOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMoreOpen(false);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [moreOpen]);

  const pill = (active: boolean) =>
    `grid h-8 w-14 place-items-center rounded-full transition-colors ${active ? 'bg-ink text-white' : 'text-ink-soft'}`;
  const tab = 'flex h-16 w-full flex-col items-center justify-center gap-0.5 text-xs font-semibold';

  return (
    <div className="lg:hidden">
      {moreOpen && (
        <>
          <button type="button" aria-label="더 보기 닫기" onClick={() => setMoreOpen(false)} className="fixed inset-0 z-20 cursor-default bg-ink/30" />
          <ul
            aria-label="더 보기"
            className="fixed inset-x-3 bottom-[calc(4rem+env(safe-area-inset-bottom)+0.5rem)] z-20 mx-auto max-w-[456px] rounded-2xl border border-line bg-surface p-2 shadow-[0_12px_32px_-12px_rgb(20_33_61/0.35)]"
          >
            {MORE_ITEMS.map(({ label, route: target, icon: Icon }) => (
              <li key={target}>
                <button
                  type="button"
                  onClick={() => go(target)}
                  aria-current={target === current ? 'page' : undefined}
                  className={`flex min-h-12 w-full items-center gap-3 rounded-xl px-3 text-left font-semibold ${
                    target === current ? 'bg-ink text-white' : 'text-ink active:bg-paper'
                  }`}
                >
                  <Icon size={20} aria-hidden />
                  {label}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      <nav aria-label="하단 메뉴" className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]">
        <ul className="mx-auto grid max-w-[480px] grid-cols-5">
          {TAB_ITEMS.map(({ label, route: target, icon: Icon }) => {
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
          <li>
            <button
              type="button"
              onClick={() => setMoreOpen((open) => !open)}
              aria-expanded={moreOpen}
              aria-haspopup="true"
              className={`${tab} ${moreActive || moreOpen ? 'text-ink' : 'text-ink-soft'}`}
            >
              <span className={pill(moreActive || moreOpen)}>
                <MoreIcon size={22} aria-hidden />
              </span>
              더 보기
            </button>
          </li>
        </ul>
      </nav>
    </div>
  );
}
